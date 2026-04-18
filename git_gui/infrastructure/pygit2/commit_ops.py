from __future__ import annotations
from datetime import datetime
import logging
import subprocess

import pygit2

from git_gui.resources import subprocess_kwargs
from git_gui.domain.entities import Commit, CommitStat, FileStat, FileStatus, Hunk, ResetMode
from git_gui.infrastructure.pygit2._helpers import _commit_to_entity, _diff_to_hunks

logger = logging.getLogger(__name__)


class CommitOps:
    """Commit reads (log/graph/stats/range/ancestor) + commit writes
    (create, amend, reset, cherry-pick, revert) + `_get_signature`.

    Mixin — not instantiable on its own. Relies on `self._repo` and
    `self._commit_ops` set up by the composite class.
    """
    _repo: pygit2.Repository  # provided by the composite

    # ── METHODS COPIED VERBATIM from Pygit2Repository ─────────────────

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

    def is_ancestor(self, ancestor_oid: str, descendant_oid: str) -> bool:
        if ancestor_oid == descendant_oid:
            return False
        return bool(self._repo.descendant_of(descendant_oid, ancestor_oid))

    # ----------------------------------------------------------------- helpers

    def _get_signature(self) -> pygit2.Signature:
        try:
            return self._repo.default_signature
        except pygit2.GitError:
            return pygit2.Signature("Git GUI", "gitgui@localhost")

    # ----------------------------------------------------------------- writes

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
