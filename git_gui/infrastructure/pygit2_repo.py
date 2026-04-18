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
from git_gui.infrastructure.pygit2.remote_ops import RemoteOps
from git_gui.infrastructure.pygit2.repo_state_ops import RepoStateOps
from git_gui.infrastructure.pygit2.stage_ops import StageOps
from git_gui.infrastructure.pygit2.commit_ops import CommitOps
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


class Pygit2Repository(StashOps, TagOps, BranchOps, RemoteOps, RepoStateOps, StageOps, CommitOps):
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

    # ------------------------------------------------------------------ reads

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

    # ----------------------------------------------------------------- writes

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

    def _rebase_onto(self, target_oid) -> None:
        # Convert Oid to hex string if needed
        target_hex = str(target_oid)
        self._run_git("rebase", target_hex)

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
