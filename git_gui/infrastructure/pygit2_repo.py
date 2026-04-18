from __future__ import annotations
from datetime import datetime, timezone
import logging
import os
import subprocess

import pygit2

from git_gui.resources import subprocess_kwargs
from git_gui.infrastructure.commit_ops_cli import CommitOpsCli
from git_gui.infrastructure.pygit2.stash_ops import StashOps
from git_gui.infrastructure.pygit2.tag_ops import TagOps
from git_gui.infrastructure.pygit2.branch_ops import BranchOps
from git_gui.infrastructure.pygit2._helpers import (
    _map_statuses,
    _commit_to_entity,
    _diff_to_hunks,
    _synthesise_untracked_hunk,
    _synthesise_conflict_hunk,
    _resolve_gitdir,
    _parse_gitmodules_paths,
    _read_submodule_head_oid,
    _submodule_diff_hunk,
)

logger = logging.getLogger(__name__)
from git_gui.domain.entities import (
    Branch, Commit, CommitStat, FileStat, FileStatus, Hunk, LocalBranchInfo, MergeAnalysisResult, MergeStrategy, Remote, RepoState, RepoStateInfo, ResetMode, Stash, Submodule, Tag, WORKING_TREE_OID,
)


class Pygit2Repository(StashOps, TagOps, BranchOps):
    def __init__(self, path: str) -> None:
        self._repo = pygit2.Repository(_resolve_gitdir(path))
        self._commit_ops = CommitOpsCli(self._repo.workdir)

    def _detect_diverged_submodules(self) -> list[tuple[str, str, str, str]]:
        """Return ``(path, tree_oid, index_oid, actual_oid)`` for each submodule
        where at least one of the three oids differs.

        Surfaces submodule changes that pygit2's ``status()``/``diff()`` misses
        when the submodule workdir has no ``.git`` link file (an "uninitialized"
        or broken checkout). The gitdir is still found via ``_resolve_gitdir``.
        """
        if self._repo.head_is_unborn:
            return []
        result: list[tuple[str, str, str, str]] = []
        try:
            head_tree = self._repo.head.peel(pygit2.Commit).tree
            index = self._repo.index
            for sub_path in _parse_gitmodules_paths(self._repo.workdir):
                try:
                    tree_oid = str(head_tree[sub_path].id)
                except KeyError:
                    continue
                try:
                    index_oid = str(index[sub_path].id)
                except KeyError:
                    index_oid = tree_oid
                actual_oid = _read_submodule_head_oid(self._repo.workdir, sub_path)
                if actual_oid is None:
                    continue
                if tree_oid != index_oid or index_oid != actual_oid:
                    result.append((sub_path, tree_oid, index_oid, actual_oid))
        except Exception as e:
            logger.warning("Failed to detect submodule changes: %s", e)
        return result

    @property
    def _git_env(self) -> dict:
        """Environment dict forcing git CLI to use this repo's gitdir/worktree.

        Without this, ``subprocess.run(["git", ...], cwd=workdir)`` lets git
        walk up looking for ``.git`` — which for a submodule workdir that
        has no ``.git`` file lands on the *parent* repo and runs the command
        against the wrong remote.
        """
        env = os.environ.copy()
        env["GIT_DIR"] = self._repo.path
        if self._repo.workdir:
            env["GIT_WORK_TREE"] = self._repo.workdir
        return env

    # ------------------------------------------------------------------ reads

    def get_commits(self, limit: int, skip: int = 0, extra_tips: list[str] | None = None) -> list[Commit]:
        if self._repo.head_is_unborn:
            return []

        walker = self._repo.walk(
            self._repo.head.target,
            pygit2.GIT_SORT_TOPOLOGICAL | pygit2.GIT_SORT_TIME,
        )

        # Also push upstream remote branch if current branch has one
        try:
            head_ref = self._repo.head
            if not head_ref.name.startswith("refs/heads/"):
                pass  # detached HEAD — no upstream
            else:
                local_name = head_ref.name[len("refs/heads/"):]
                local_branch = self._repo.branches.local[local_name]
                if local_branch.upstream:
                    walker.push(local_branch.upstream.resolve().target)
        except (KeyError, Exception):
            pass

        # Push extra tips (e.g. clicked branch)
        for tip in (extra_tips or []):
            try:
                walker.push(pygit2.Oid(hex=tip))
            except (ValueError, Exception):
                pass

        # Skip first N commits
        for _ in range(skip):
            try:
                next(walker)
            except StopIteration:
                return []
        return [_commit_to_entity(c) for c, _ in zip(walker, range(limit))]

    def get_commit(self, oid: str) -> Commit:
        obj = self._repo.get(oid)
        if obj is None:
            raise KeyError(f"Commit not found: {oid}")
        return _commit_to_entity(obj)

    def get_commit_range(self, head_oid: str, base_oid: str) -> list[Commit]:
        """Return commits from head_oid back to base_oid (exclusive), oldest-first.

        Computes the merge-base between head_oid and base_oid first (matching
        ``git rebase -i`` behavior — the actual stopping point is the merge-base,
        not the target tip). Follows first-parent only so merge side-branches
        are excluded. Returns the commits in oldest-first order.
        """
        if head_oid == base_oid:
            return []
        # Compute the merge-base — this is where git rebase -i actually stops.
        # If target has advanced past the branch point, using the target tip
        # directly would walk all the way to the root.
        try:
            mb = self._repo.merge_base(head_oid, base_oid)
            stop_oid = str(mb)
        except Exception:
            stop_oid = base_oid
        if head_oid == stop_oid:
            return []
        walker = self._repo.walk(
            head_oid,
            pygit2.GIT_SORT_TOPOLOGICAL | pygit2.GIT_SORT_TIME,
        )
        walker.simplify_first_parent()
        collected: list[Commit] = []
        for c in walker:
            if str(c.id) == stop_oid:
                break
            collected.append(_commit_to_entity(c))
        collected.reverse()
        return collected

    def get_commit_files(self, oid: str) -> list[FileStatus]:
        commit = self._repo.get(oid)
        if commit.parents:
            diff = self._repo.diff(commit.parents[0].tree, commit.tree)
        else:
            # Initial commit: diff from empty tree to commit tree so files show as added
            empty_tree_oid = self._repo.TreeBuilder().write()
            empty_tree = self._repo.get(empty_tree_oid)
            diff = self._repo.diff(empty_tree, commit.tree)
        files = []
        for patch in diff:
            delta = patch.delta
            path = delta.new_file.path or delta.old_file.path
            delta_type = {
                pygit2.GIT_DELTA_ADDED:    "added",
                pygit2.GIT_DELTA_DELETED:  "deleted",
                pygit2.GIT_DELTA_MODIFIED: "modified",
                pygit2.GIT_DELTA_RENAMED:  "renamed",
            }.get(delta.status, "unknown")
            files.append(FileStatus(path=path, status="staged", delta=delta_type))
        return files

    def get_file_diff(self, oid: str, path: str) -> list[Hunk]:
        if oid == WORKING_TREE_OID:
            diff = self._repo.diff()
            for patch in diff:
                if patch.delta.new_file.path == path or patch.delta.old_file.path == path:
                    hunks = _diff_to_hunks(patch)
                    if hunks:
                        return hunks
                    # Patch found but 0 hunks (e.g. conflicted) — fall through
                    break
            # Not found in tracked diff, or found with 0 hunks — check status
            try:
                status = self._repo.status_file(path)
            except KeyError:
                return []
            if status & pygit2.GIT_STATUS_CONFLICTED:
                hunks = _synthesise_conflict_hunk(self._repo.workdir, path)
                if hunks:
                    return hunks
                # Conflict markers resolved — diff working tree against HEAD
                return self._diff_workfile_against_head(path)
            if status & pygit2.GIT_STATUS_WT_NEW:
                return _synthesise_untracked_hunk(self._repo.workdir, path)
            return []
        commit = self._repo.get(oid)
        if commit.parents:
            diff = self._repo.diff(commit.parents[0].tree, commit.tree)
        else:
            empty_tree_oid = self._repo.TreeBuilder().write()
            empty_tree = self._repo.get(empty_tree_oid)
            diff = self._repo.diff(empty_tree, commit.tree)
        for patch in diff:
            if patch.delta.new_file.path == path or patch.delta.old_file.path == path:
                return _diff_to_hunks(patch)
        return []

    def get_commit_diff_map(self, oid: str) -> dict[str, list[Hunk]]:
        """Return a dict of {path: [Hunk, ...]} for every changed file in the commit.

        Computes the full tree diff exactly once, instead of the per-file diff pattern.
        """
        commit = self._repo.get(oid)
        if commit.parents:
            diff = self._repo.diff(commit.parents[0].tree, commit.tree)
        else:
            empty_tree_oid = self._repo.TreeBuilder().write()
            empty_tree = self._repo.get(empty_tree_oid)
            diff = self._repo.diff(empty_tree, commit.tree)
        result: dict[str, list[Hunk]] = {}
        for patch in diff:
            path = patch.delta.new_file.path or patch.delta.old_file.path
            if path:
                result[path] = _diff_to_hunks(patch)
        return result

    def get_working_tree_diff_map(self) -> dict[str, dict[str, list[Hunk]]]:
        """Return {path: {"staged": [...], "unstaged": [...]}} for every changed file.

        Computes the full staged diff and unstaged diff exactly once each.
        """
        result: dict[str, dict[str, list[Hunk]]] = {}

        # Staged: index vs HEAD
        try:
            if self._repo.head_is_unborn:
                empty_tree_oid = self._repo.TreeBuilder().write()
                empty_tree = self._repo.get(empty_tree_oid)
                staged_diff = self._repo.index.diff_to_tree(empty_tree)
            else:
                head_commit = self._repo.head.peel(pygit2.Commit)
                staged_diff = self._repo.index.diff_to_tree(head_commit.tree)
            for patch in staged_diff:
                path = patch.delta.new_file.path or patch.delta.old_file.path
                if not path:
                    continue
                result.setdefault(path, {"staged": [], "unstaged": []})
                result[path]["staged"] = _diff_to_hunks(patch)
        except Exception as e:
            logger.warning("Failed to compute staged diff map: %s", e)

        # Unstaged: workdir vs index
        try:
            unstaged_diff = self._repo.diff()
            for patch in unstaged_diff:
                path = patch.delta.new_file.path or patch.delta.old_file.path
                if not path:
                    continue
                result.setdefault(path, {"staged": [], "unstaged": []})
                hunks = _diff_to_hunks(patch)
                if not hunks:
                    try:
                        status = self._repo.status_file(path)
                    except KeyError:
                        status = 0
                    if status & pygit2.GIT_STATUS_CONFLICTED:
                        conflict_hunks = _synthesise_conflict_hunk(self._repo.workdir, path)
                        if conflict_hunks:
                            hunks = conflict_hunks
                        else:
                            hunks = self._diff_workfile_against_head(path)
                result[path]["unstaged"] = hunks
        except Exception as e:
            logger.warning("Failed to compute unstaged diff map: %s", e)

        # Untracked files
        try:
            for path, status in self._repo.status().items():
                if status & pygit2.GIT_STATUS_WT_NEW:
                    result.setdefault(path, {"staged": [], "unstaged": []})
                    result[path]["unstaged"] = _synthesise_untracked_hunk(self._repo.workdir, path)
        except Exception as e:
            logger.warning("Failed to enumerate untracked files for diff map: %s", e)

        # Submodule changes that pygit2's diff() misses for uninitialized workdirs.
        # Override any existing empty entry — pygit2 sometimes returns an empty
        # patch for a submodule, which would leave the UI with no hunks to show.
        for sub_path, tree_oid, index_oid, actual_oid in self._detect_diverged_submodules():
            entry = result.setdefault(sub_path, {"staged": [], "unstaged": []})
            if index_oid != tree_oid:
                entry["staged"] = [_submodule_diff_hunk(tree_oid, index_oid)]
            if actual_oid != index_oid:
                entry["unstaged"] = [_submodule_diff_hunk(index_oid, actual_oid)]

        return result

    def _diff_workfile_against_head(self, path: str) -> list[Hunk]:
        """Diff the working-tree file against the HEAD version."""
        try:
            head_commit = self._repo.head.peel(pygit2.Commit)
            diff = self._repo.diff(head_commit.tree, flags=pygit2.GIT_DIFF_FORCE_TEXT)
            for patch in diff:
                if patch.delta.new_file.path == path or patch.delta.old_file.path == path:
                    return _diff_to_hunks(patch)
        except Exception as e:
            logger.warning("Failed to diff %r against HEAD: %s", path, e)
        return []

    def get_staged_diff(self, path: str) -> list[Hunk]:
        # Diff the index against HEAD tree to show what is staged for commit.
        # For unborn HEAD (no commits yet), diff against an empty tree.
        # When the index has conflicts, diff_to_tree may fail — return empty.
        try:
            if self._repo.head_is_unborn:
                empty_tree_oid = self._repo.TreeBuilder().write()
                empty_tree = self._repo.get(empty_tree_oid)
                diff = self._repo.index.diff_to_tree(empty_tree)
            else:
                head_commit = self._repo.head.peel(pygit2.Commit)
                diff = self._repo.index.diff_to_tree(head_commit.tree)
            for patch in diff:
                if patch.delta.new_file.path == path or patch.delta.old_file.path == path:
                    return _diff_to_hunks(patch)
        except Exception as e:
            logger.warning("Failed to compute staged diff for %r: %s", path, e)
        return []

    def get_commit_stats(self, since: datetime | None = None, until: datetime | None = None) -> list[CommitStat]:
        cmd = ["git", "log", "--numstat", "--format=__COMMIT__%n%H%n%aN <%aE>%n%aI"]
        if since:
            cmd.append(f"--since={since.isoformat()}")
        if until:
            cmd.append(f"--until={until.isoformat()}")
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                cwd=self._repo.workdir, env=self._git_env, **subprocess_kwargs(),
            )
            if result.returncode != 0:
                return []
        except Exception as e:
            logger.warning("Failed to run git log for commit stats: %s", e)
            return []

        stats: list[CommitStat] = []
        current_oid: str | None = None
        current_author: str | None = None
        current_ts: datetime | None = None
        current_files: list[FileStat] = []
        state = "expect_marker"  # expect_marker | oid | author | date | files

        def flush() -> None:
            if current_oid and current_author and current_ts is not None:
                stats.append(CommitStat(
                    oid=current_oid,
                    author=current_author,
                    timestamp=current_ts,
                    files=list(current_files),
                ))

        for raw_line in result.stdout.splitlines():
            line = raw_line.rstrip("\r")
            if line == "__COMMIT__":
                flush()
                current_oid = None
                current_author = None
                current_ts = None
                current_files = []
                state = "oid"
                continue
            if state == "oid":
                current_oid = line
                state = "author"
                continue
            if state == "author":
                current_author = line
                state = "date"
                continue
            if state == "date":
                try:
                    current_ts = datetime.fromisoformat(line)
                except ValueError:
                    current_ts = None
                state = "files"
                continue
            if state == "files":
                if not line.strip():
                    continue
                # numstat format: "<added>\t<deleted>\t<path>"
                parts = line.split("\t")
                if len(parts) != 3:
                    continue
                added_str, deleted_str, path = parts
                try:
                    added = int(added_str) if added_str != "-" else 0
                    deleted = int(deleted_str) if deleted_str != "-" else 0
                except ValueError:
                    continue
                current_files.append(FileStat(path=path, added=added, deleted=deleted))

        flush()
        return stats

    def get_working_tree(self) -> list[FileStatus]:
        files = []
        for path, flags in self._repo.status().items():
            if flags == pygit2.GIT_STATUS_CURRENT:
                continue
            for status, delta in _map_statuses(flags):
                files.append(FileStatus(path=path, status=status, delta=delta))

        # Surface submodule changes that pygit2's status() misses when the
        # submodule workdir has no .git link file.
        seen = {f.path for f in files}
        for sub_path, tree_oid, index_oid, actual_oid in self._detect_diverged_submodules():
            if sub_path in seen:
                continue
            if index_oid != tree_oid:
                files.append(FileStatus(path=sub_path, status="staged", delta="modified"))
            if actual_oid != index_oid:
                files.append(FileStatus(path=sub_path, status="unstaged", delta="modified"))

        return files

    def is_dirty(self) -> bool:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True,
            cwd=self._repo.workdir, env=self._git_env, **subprocess_kwargs(),
        )
        return bool(result.stdout.strip())

    def get_head_oid(self) -> str | None:
        if self._repo.head_is_unborn:
            return None
        return str(self._repo.head.target)

    def is_ancestor(self, ancestor_oid: str, descendant_oid: str) -> bool:
        if ancestor_oid == descendant_oid:
            return False
        return bool(self._repo.descendant_of(descendant_oid, ancestor_oid))

    def repo_state(self) -> RepoStateInfo:
        # Unborn HEAD (fresh `git init`, no commits yet) — CLEAN with no branch.
        if self._repo.head_is_unborn:
            return RepoStateInfo(state=RepoState.CLEAN, head_branch=None)

        # Check operation state FIRST — git detaches HEAD during rebase,
        # but we want to report REBASING, not DETACHED_HEAD.
        state = self._repo.state()
        raw_map = {
            "GIT_REPOSITORY_STATE_NONE": RepoState.CLEAN,
            "GIT_REPOSITORY_STATE_MERGE": RepoState.MERGING,
            "GIT_REPOSITORY_STATE_REVERT": RepoState.REVERTING,
            "GIT_REPOSITORY_STATE_CHERRYPICK": RepoState.CHERRY_PICKING,
            "GIT_REPOSITORY_STATE_REBASE": RepoState.REBASING,
            "GIT_REPOSITORY_STATE_REBASE_INTERACTIVE": RepoState.REBASING,
            "GIT_REPOSITORY_STATE_REBASE_MERGE": RepoState.REBASING,
            "GIT_REPOSITORY_STATE_APPLY_MAILBOX": RepoState.CLEAN,
            "GIT_REPOSITORY_STATE_APPLY_MAILBOX_OR_REBASE": RepoState.REBASING,
        }
        state_map: dict[int, RepoState] = {}
        for name, mapped_state in raw_map.items():
            const = getattr(pygit2, name, None)
            if const is not None:
                state_map[const] = mapped_state
        mapped = state_map.get(state, RepoState.CLEAN)

        # If in an active operation (merge/rebase/etc), report that state
        # even if HEAD is detached (rebase detaches HEAD).
        if mapped != RepoState.CLEAN:
            head_branch = None if self._repo.head_is_detached else self._repo.head.shorthand
            return RepoStateInfo(state=mapped, head_branch=head_branch)

        # No operation in progress — check for plain detached HEAD
        if self._repo.head_is_detached:
            return RepoStateInfo(state=RepoState.DETACHED_HEAD, head_branch=None)

        return RepoStateInfo(state=RepoState.CLEAN, head_branch=self._repo.head.shorthand)

    def get_merge_head(self) -> str | None:
        merge_head_path = os.path.join(self._repo.path, "MERGE_HEAD")
        if not os.path.exists(merge_head_path):
            return None
        with open(merge_head_path) as f:
            return f.readline().strip()

    def get_merge_msg(self) -> str | None:
        merge_msg_path = os.path.join(self._repo.path, "MERGE_MSG")
        if not os.path.exists(merge_msg_path):
            return None
        with open(merge_msg_path) as f:
            return f.read()

    def has_unresolved_conflicts(self) -> bool:
        self._repo.index.read()
        if self._repo.index.conflicts is None:
            return False
        try:
            next(iter(self._repo.index.conflicts))
            return True
        except StopIteration:
            return False

    # ----------------------------------------------------------------- helpers

    def _get_signature(self) -> pygit2.Signature:
        try:
            return self._repo.default_signature
        except pygit2.GitError:
            return pygit2.Signature("Git GUI", "gitgui@localhost")

    # ----------------------------------------------------------------- writes

    def stage(self, paths: list[str]) -> None:
        for path in paths:
            full = os.path.join(self._repo.workdir, path)
            if os.path.exists(full):
                self._repo.index.add(path)
            else:
                # Working-tree deletion → stage the deletion
                try:
                    self._repo.index.remove(path)
                except (KeyError, OSError):
                    pass
        self._repo.index.write()

    def unstage(self, paths: list[str]) -> None:
        if self._repo.head_is_unborn:
            for path in paths:
                self._repo.index.remove(path)
            self._repo.index.write()
        else:
            head_commit = self._repo.head.peel(pygit2.Commit)
            for path in paths:
                if path in head_commit.tree:
                    entry = head_commit.tree[path]
                    self._repo.index.add(
                        pygit2.IndexEntry(path, entry.id, entry.filemode)
                    )
                else:
                    self._repo.index.remove(path)
            self._repo.index.write()

    def stage_hunk(self, path: str, hunk_header: str) -> None:
        patch = self._build_hunk_patch(path, hunk_header, staged=False)
        if patch:
            subprocess.run(
                ["git", "apply", "--cached"],
                input=patch.encode("utf-8"), cwd=self._repo.workdir,
                env=self._git_env,
                check=True, capture_output=True, **subprocess_kwargs(),
            )
            self._repo.index.read()

    def unstage_hunk(self, path: str, hunk_header: str) -> None:
        patch = self._build_hunk_patch(path, hunk_header, staged=True)
        if patch:
            subprocess.run(
                ["git", "apply", "--cached", "--reverse"],
                input=patch.encode("utf-8"), cwd=self._repo.workdir,
                env=self._git_env,
                check=True, capture_output=True, **subprocess_kwargs(),
            )
            self._repo.index.read()

    def discard_file(self, path: str) -> None:
        full = os.path.join(self._repo.workdir, path)
        head_has_blob = False
        head_commit = None
        if not self._repo.head_is_unborn:
            head_commit = self._repo.head.peel(pygit2.Commit)
            try:
                head_commit.tree[path]
                head_has_blob = True
            except KeyError:
                head_has_blob = False

        if head_has_blob:
            entry = head_commit.tree[path]
            self._repo.index.add(
                pygit2.IndexEntry(path, entry.id, entry.filemode)
            )
            self._repo.index.write()
            self._repo.index.read()
            blob = self._repo.get(entry.id)
            os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
            with open(full, "wb") as f:
                f.write(blob.data)
        else:
            try:
                self._repo.index.remove(path)
                self._repo.index.write()
                self._repo.index.read()
            except (KeyError, OSError):
                pass
            if os.path.exists(full):
                os.remove(full)

    def discard_hunk(self, path: str, hunk_header: str) -> None:
        patch = self._build_hunk_patch(path, hunk_header, staged=False)
        if patch:
            subprocess.run(
                ["git", "apply", "--reverse"],
                input=patch.encode("utf-8"), cwd=self._repo.workdir,
                env=self._git_env,
                check=True, capture_output=True, **subprocess_kwargs(),
            )
            self._repo.index.read()

    def _build_hunk_patch(self, path: str, hunk_header: str, staged: bool) -> str | None:
        if staged:
            if self._repo.head_is_unborn:
                empty_tree_oid = self._repo.TreeBuilder().write()
                empty_tree = self._repo.get(empty_tree_oid)
                diff = self._repo.index.diff_to_tree(empty_tree)
            else:
                head_commit = self._repo.head.peel(pygit2.Commit)
                diff = self._repo.index.diff_to_tree(head_commit.tree)
        else:
            diff = self._repo.diff()

        for patch in diff:
            if patch.delta.new_file.path != path and patch.delta.old_file.path != path:
                continue
            for hunk in patch.hunks:
                if hunk.header == hunk_header:
                    # Build minimal patch: diff header + single hunk
                    lines = [f"--- a/{path}\n", f"+++ b/{path}\n"]
                    lines.append(hunk.header)
                    for line in hunk.lines:
                        lines.append(f"{line.origin}{line.content}")
                    # Ensure last line ends with newline
                    if lines and not lines[-1].endswith("\n"):
                        lines[-1] += "\n"
                    return "".join(lines)
        return None

    def commit(self, message: str) -> "Commit":
        self._repo.index.write()
        tree = self._repo.index.write_tree()
        sig = self._get_signature()
        parents = [] if self._repo.head_is_unborn else [self._repo.head.target]
        # During a merge, include MERGE_HEAD as second parent
        merge_head = self.get_merge_head()
        if merge_head:
            parents.append(pygit2.Oid(hex=merge_head))
        oid = self._repo.create_commit("HEAD", sig, sig, message, tree, parents)
        # Clean up merge state files after successful merge commit
        if merge_head:
            self._repo.state_cleanup()
        return _commit_to_entity(self._repo.get(oid))

    def merge(self, branch: str, strategy: MergeStrategy = MergeStrategy.ALLOW_FF, message: str | None = None) -> None:
        if branch in self._repo.branches.local:
            ref = self._repo.branches.local[branch]
        else:
            ref = self._repo.branches.remote[branch]
        default_label = f"branch '{branch}'"
        self._merge_oid(ref.target, label=default_label, strategy=strategy, message=message)

    def merge_commit(self, oid: str, strategy: MergeStrategy = MergeStrategy.ALLOW_FF, message: str | None = None) -> None:
        target = pygit2.Oid(hex=oid)
        default_label = f"commit {oid[:7]}"
        self._merge_oid(target, label=default_label, strategy=strategy, message=message)

    def merge_analysis(self, oid: str) -> MergeAnalysisResult:
        target = pygit2.Oid(hex=oid)
        result, _ = self._repo.merge_analysis(target)
        can_ff = bool(result & pygit2.GIT_MERGE_ANALYSIS_FASTFORWARD)
        is_up_to_date = bool(result & pygit2.GIT_MERGE_ANALYSIS_UP_TO_DATE)
        return MergeAnalysisResult(can_ff=can_ff, is_up_to_date=is_up_to_date)

    def _merge_oid(self, target_oid, label: str, strategy: MergeStrategy = MergeStrategy.ALLOW_FF, message: str | None = None) -> None:
        merge_result, _ = self._repo.merge_analysis(target_oid)
        can_ff = bool(merge_result & pygit2.GIT_MERGE_ANALYSIS_FASTFORWARD)
        commit_message = message if message else f"Merge {label}"

        if strategy == MergeStrategy.FF_ONLY:
            if can_ff:
                self._repo.checkout_tree(self._repo.get(target_oid))
                self._repo.head.set_target(target_oid)
            else:
                raise RuntimeError("Cannot fast-forward this merge")
        elif strategy == MergeStrategy.NO_FF:
            self._repo.merge(target_oid)
            if not self._repo.index.conflicts:
                self._repo.index.write()
                tree = self._repo.index.write_tree()
                sig = self._get_signature()
                self._repo.create_commit(
                    "HEAD", sig, sig,
                    commit_message,
                    tree,
                    [self._repo.head.target, target_oid],
                )
                self._repo.state_cleanup()
        else:  # ALLOW_FF
            if can_ff:
                self._repo.checkout_tree(self._repo.get(target_oid))
                self._repo.head.set_target(target_oid)
            elif merge_result & pygit2.GIT_MERGE_ANALYSIS_NORMAL:
                self._repo.merge(target_oid)
                if not self._repo.index.conflicts:
                    self._repo.index.write()
                    tree = self._repo.index.write_tree()
                    sig = self._get_signature()
                    self._repo.create_commit(
                        "HEAD", sig, sig,
                        commit_message,
                        tree,
                        [self._repo.head.target, target_oid],
                    )
                    self._repo.state_cleanup()

    def rebase(self, branch: str) -> None:
        onto_ref = self._repo.branches.local[branch]
        self._rebase_onto(onto_ref.target)

    def rebase_onto_commit(self, oid: str) -> None:
        self._rebase_onto(pygit2.Oid(hex=oid))

    def merge_abort(self) -> None:
        self._run_git("merge", "--abort")

    def rebase_abort(self) -> None:
        self._run_git("rebase", "--abort")

    def rebase_continue(self, message: str = "") -> None:
        import sys, tempfile
        env = self._git_env
        if message:
            # Write the message to a temp file, then set GIT_EDITOR to a
            # command that copies it over the file git passes to the editor.
            msg_file = tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8",
            )
            msg_file.write(message)
            msg_file.close()
            # Use python to copy the temp file content into the editor target
            python = sys.executable.replace("\\", "/")
            msg_path = msg_file.name.replace("\\", "/")
            env["GIT_EDITOR"] = (
                f'{python} -c "'
                f"import shutil,sys; shutil.copy('{msg_path}', sys.argv[1])"
                f'"'
            )
        else:
            env["GIT_EDITOR"] = "true"
        try:
            result = subprocess.run(
                ["git", "rebase", "--continue"],
                cwd=self._repo.workdir, capture_output=True, text=True,
                env=env, **subprocess_kwargs(),
            )
            if result.returncode != 0:
                msg = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
                raise RuntimeError(msg)
        finally:
            if message:
                try:
                    os.unlink(msg_file.name)
                except OSError:
                    pass

    def interactive_rebase(self, target_oid: str, entries: list[tuple[str, str]]) -> None:
        """Run git rebase -i with a pre-built todo file.

        *entries* is a list of (action, oid) tuples in replay order.
        Actions: "pick", "squash", "fixup", "drop".
        """
        import sys
        import tempfile

        # Use the merge-base as the actual rebase target so git's internal
        # commit list matches the one we showed in the dialog. Without this,
        # git rebase -i <target_tip> might compute a different range than
        # get_commit_range() did.
        head_oid = str(self._repo.head.target)
        try:
            mb = self._repo.merge_base(head_oid, target_oid)
            rebase_target = str(mb)
        except Exception:
            rebase_target = target_oid

        # Build the todo file content
        todo_lines = [f"{action} {oid}" for action, oid in entries]
        todo_content = "\n".join(todo_lines) + "\n"

        # Write to a temp file
        todo_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8",
        )
        todo_file.write(todo_content)
        todo_file.close()

        env = self._git_env
        python = sys.executable.replace("\\", "/")
        todo_path = todo_file.name.replace("\\", "/")
        env["GIT_SEQUENCE_EDITOR"] = (
            f'{python} -c "'
            f"import shutil,sys; shutil.copy('{todo_path}', sys.argv[1])"
            f'"'
        )
        # Prevent interactive editor from opening for squash/fixup messages
        env["GIT_EDITOR"] = "true"

        try:
            result = subprocess.run(
                ["git", "rebase", "-i", rebase_target],
                cwd=self._repo.workdir, capture_output=True, text=True,
                env=env, **subprocess_kwargs(),
            )
            if result.returncode != 0:
                # Check if we're in a conflict state — let the banner handle it
                state = self._repo.state()
                rebase_states = set()
                for name in ("GIT_REPOSITORY_STATE_REBASE",
                             "GIT_REPOSITORY_STATE_REBASE_INTERACTIVE",
                             "GIT_REPOSITORY_STATE_REBASE_MERGE"):
                    const = getattr(pygit2, name, None)
                    if const is not None:
                        rebase_states.add(const)
                if state in rebase_states:
                    return  # conflict — Spec C banner will handle
                msg = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
                raise RuntimeError(msg)
        finally:
            try:
                os.unlink(todo_file.name)
            except OSError:
                pass

    def cherry_pick(self, oid: str) -> None:
        commit = self._repo[pygit2.Oid(hex=oid)]
        is_merge = len(commit.parents) > 1
        self._commit_ops.cherry_pick(oid, is_merge=is_merge)

    def revert_commit(self, oid: str) -> None:
        commit = self._repo[pygit2.Oid(hex=oid)]
        is_merge = len(commit.parents) > 1
        self._commit_ops.revert_commit(oid, is_merge=is_merge)

    def reset_to(self, oid: str, mode: ResetMode) -> None:
        pygit2_type = {
            ResetMode.SOFT: pygit2.GIT_RESET_SOFT,
            ResetMode.MIXED: pygit2.GIT_RESET_MIXED,
            ResetMode.HARD: pygit2.GIT_RESET_HARD,
        }[mode]
        self._repo.reset(pygit2.Oid(hex=oid), pygit2_type)

    def cherry_pick_abort(self) -> None:
        self._commit_ops.cherry_pick_abort()

    def cherry_pick_continue(self) -> None:
        self._commit_ops.cherry_pick_continue()

    def revert_abort(self) -> None:
        self._commit_ops.revert_abort()

    def revert_continue(self) -> None:
        self._commit_ops.revert_continue()

    def _rebase_onto(self, target_oid) -> None:
        # Convert Oid to hex string if needed
        target_hex = str(target_oid)
        self._run_git("rebase", target_hex)

    def push(self, remote: str, branch: str) -> None:
        self._run_git("push", remote, branch)

    def force_push(self, remote: str, branch: str) -> None:
        self._run_git("push", "--force-with-lease", remote, branch)

    def pull(self, remote: str, branch: str) -> None:
        self._run_git("pull", "--rebase", remote, branch)

    def fetch(self, remote: str) -> None:
        self._run_git("fetch", remote)

    def fetch_all_prune(self) -> None:
        self._run_git("fetch", "--all", "--prune")

    def _run_git(self, *args: str) -> None:
        result = subprocess.run(
            ["git", *args],
            cwd=self._repo.workdir, capture_output=True, text=True,
            env=self._git_env, **subprocess_kwargs(),
        )
        if result.returncode != 0:
            msg = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
            raise RuntimeError(msg)

    # ----- Remotes -----

    def list_remotes(self) -> list[Remote]:
        result: list[Remote] = []
        for r in self._repo.remotes:
            push_url = r.push_url if r.push_url else r.url
            result.append(Remote(name=r.name, fetch_url=r.url, push_url=push_url))
        return result

    def add_remote(self, name: str, url: str) -> None:
        self._repo.remotes.create(name, url)

    def remove_remote(self, name: str) -> None:
        self._repo.remotes.delete(name)

    def rename_remote(self, old_name: str, new_name: str) -> None:
        self._repo.remotes.rename(old_name, new_name)

    def set_remote_url(self, name: str, url: str) -> None:
        self._repo.remotes.set_url(name, url)

    # ----- Submodules -----

    def _submodule_cli(self):
        from git_gui.infrastructure.submodule_cli import SubmoduleCli
        return SubmoduleCli(self._repo.workdir)

    def list_submodules(self) -> list[Submodule]:
        result: list[Submodule] = []
        try:
            sm_paths = list(self._repo.listall_submodules())
        except Exception as e:
            logger.warning("Failed to list submodules: %s", e)
            return result
        if not sm_paths:
            return result

        # Parse URLs from .gitmodules config file
        import os
        url_map: dict[str, str] = {}
        gitmodules_path = os.path.join(self._repo.workdir, ".gitmodules")
        if os.path.exists(gitmodules_path):
            try:
                cfg = pygit2.Config(gitmodules_path)
                for entry in cfg:
                    # entry.name is like "submodule.libs/foo.url"
                    parts = entry.name.split(".")
                    if len(parts) >= 3 and parts[0] == "submodule" and parts[-1] == "url":
                        sm_path = ".".join(parts[1:-1])
                        url_map[sm_path] = entry.value
            except Exception as e:
                logger.warning("Failed to parse .gitmodules at %r: %s", gitmodules_path, e)

        # Get head SHAs via git ls-files -s (gitlink entries have mode 160000)
        sha_map: dict[str, str] = {}
        try:
            ls_result = subprocess.run(
                ["git", "ls-files", "-s", "--"] + sm_paths,
                capture_output=True, text=True,
                cwd=self._repo.workdir, env=self._git_env, **subprocess_kwargs(),
            )
            for line in ls_result.stdout.splitlines():
                # Format: "160000 <sha> <stage>\t<path>"
                line_parts = line.split("\t", 1)
                if len(line_parts) == 2:
                    fields = line_parts[0].split()
                    if len(fields) >= 2 and fields[0] == "160000":
                        sha_map[line_parts[1]] = fields[1]
        except Exception as e:
            logger.warning("Failed to read submodule SHAs via git ls-files: %s", e)

        for path in sm_paths:
            url = url_map.get(path, "")
            head = sha_map.get(path)
            result.append(Submodule(path=path, url=url, head_sha=head))
        return result

    def add_submodule(self, path: str, url: str) -> None:
        self._submodule_cli().add(path=path, url=url)

    def remove_submodule(self, path: str) -> None:
        self._submodule_cli().remove(path)

    def set_submodule_url(self, path: str, url: str) -> None:
        self._submodule_cli().set_url(path, url)
