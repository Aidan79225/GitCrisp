from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable, Iterator
from datetime import datetime

import pygit2

from git_gui.domain.entities import Commit, CommitStat, FileStat, FileStatus, Hunk, ResetMode
from git_gui.infrastructure.file_history_cli import FileHistoryCli
from git_gui.infrastructure.pygit2._helpers import _commit_to_entity, _diff_to_hunks
from git_gui.resources import subprocess_kwargs

logger = logging.getLogger(__name__)


class CommitOps:
    """Commit reads (log/graph/stats/range/ancestor) + commit writes
    (create, amend, reset, cherry-pick, revert) + `_get_signature`.

    Mixin — not instantiable on its own. Relies on `self._repo` and
    `self._commit_ops` set up by the composite class.
    """

    _repo: pygit2.Repository  # provided by the composite
    _file_history: FileHistoryCli  # provided by the composite

    # ── METHODS COPIED VERBATIM from Pygit2Repository ─────────────────

    def get_commits(
        self,
        limit: int,
        skip: int = 0,
        extra_tips: list[str] | None = None,
        *,
        first_parent: bool = False,
    ) -> list[Commit]:
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
                local_name = head_ref.name[len("refs/heads/") :]
                local_branch = self._repo.branches.local[local_name]
                if local_branch.upstream:
                    walker.push(local_branch.upstream.resolve().target)
        except (KeyError, Exception):
            pass

        # Push extra tips (e.g. clicked branch)
        for tip in extra_tips or []:
            try:
                walker.push(pygit2.Oid(hex=tip))
            except (ValueError, Exception):
                pass

        if first_parent:
            walker.simplify_first_parent()

        # Skip first N commits
        for _ in range(skip):
            try:
                next(walker)
            except StopIteration:
                return []
        result = [_commit_to_entity(c) for c, _ in zip(walker, range(limit), strict=False)]

        # Guarantee the requested tips are present even when they sort beyond
        # `limit` in the topological/time-ordered walk (e.g. an old branch tip
        # that predates many newer mainline commits). Without this, callers
        # can't locate/scroll to such a tip. Appended in time-descending order
        # so the model still renders them oldest-last.
        loaded = {c.oid for c in result}
        missing: list[Commit] = []
        for tip in extra_tips or []:
            if tip in loaded:
                continue
            try:
                obj = self._repo.get(pygit2.Oid(hex=tip))
            except (ValueError, Exception):
                continue
            if obj is None:
                continue
            entity = _commit_to_entity(obj)
            if entity.oid in loaded:
                continue
            loaded.add(entity.oid)
            missing.append(entity)
        missing.sort(key=lambda c: c.timestamp, reverse=True)
        result.extend(missing)
        return result

    def get_commit(self, oid: str) -> Commit:
        obj = self._repo.get(oid)
        if obj is None:
            raise KeyError(f"Commit not found: {oid}")
        return _commit_to_entity(obj)

    def get_file_history(
        self, path: str, limit: int, skip: int = 0, *, follow: bool = True
    ) -> list[Commit]:
        """Commits touching `path`, newest first.

        The walk itself is delegated to the git CLI (see `FileHistoryCli`) —
        pygit2 offers neither a pathspec-limited revwalk nor rename following.
        Each returned OID is hydrated through the normal commit path, so the
        entities are indistinguishable from `get_commits()` output and the
        graph model can consume them unchanged.
        """
        oids = self._file_history.commit_oids(path, limit, skip, follow=follow)
        commits: list[Commit] = []
        for oid in oids:
            obj = self._repo.get(oid)
            if obj is not None:  # a commit git listed but we cannot read is skipped
                commits.append(_commit_to_entity(obj))
        return commits

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

    def merge_base(self, oid_a: str, oid_b: str) -> str | None:
        try:
            result = self._repo.merge_base(pygit2.Oid(hex=oid_a), pygit2.Oid(hex=oid_b))
        except (KeyError, ValueError, pygit2.GitError):
            return None
        return str(result) if result is not None else None

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
                pygit2.GIT_DELTA_ADDED: "added",
                pygit2.GIT_DELTA_DELETED: "deleted",
                pygit2.GIT_DELTA_MODIFIED: "modified",
                pygit2.GIT_DELTA_RENAMED: "renamed",
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

    def get_commit_stats(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        *,
        cancel: Callable[[], bool] | None = None,
    ) -> Iterator[CommitStat]:
        cmd = ["git", "log", "--numstat", "--format=__COMMIT__%n%H%n%aN <%aE>%n%aI"]
        if since:
            cmd.append(f"--since={since.isoformat()}")
        if until:
            cmd.append(f"--until={until.isoformat()}")

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                # Force UTF-8 decoding. Git emits UTF-8 by default regardless
                # of the platform's locale; relying on `text=True` alone uses
                # locale.getpreferredencoding() (e.g. cp1252 on Windows), which
                # raises UnicodeDecodeError the moment a commit author, path,
                # or message contains non-ASCII characters outside that
                # encoding's range — causing Insight to silently produce zero
                # rows on otherwise valid repos.
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                cwd=self._repo.workdir,
                env=self._git_env,
                **subprocess_kwargs(),
            )
        except Exception as e:
            logger.warning("Failed to start git log for commit stats: %s", e)
            return

        current_oid: str | None = None
        current_author: str | None = None
        current_ts: datetime | None = None
        current_files: list[FileStat] = []
        state = "expect_marker"  # expect_marker | oid | author | date | files

        def _build() -> CommitStat | None:
            if current_oid and current_author and current_ts is not None:
                return CommitStat(
                    oid=current_oid,
                    author=current_author,
                    timestamp=current_ts,
                    files=list(current_files),
                )
            return None

        try:
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                line = raw_line.rstrip("\r\n")
                if line == "__COMMIT__":
                    cs = _build()
                    if cs is not None:
                        yield cs
                        if cancel is not None and cancel():
                            return
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

            cs = _build()
            if cs is not None:
                yield cs
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                pass

    def is_ancestor(self, ancestor_oid: str, descendant_oid: str) -> bool:
        if ancestor_oid == descendant_oid:
            return False
        return bool(self._repo.descendant_of(descendant_oid, ancestor_oid))

    # ----------------------------------------------------------------- helpers

    def _get_signature(self) -> pygit2.Signature:
        return self._repo.default_signature

    # ----------------------------------------------------------------- writes

    def commit(self, message: str) -> Commit:
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

    def amend_commit(self, message: str) -> Commit:
        """Replace HEAD with a commit carrying the current index and `message`.

        The original author (name, email and time) is preserved — only the
        committer becomes the current identity, matching `git commit --amend`.
        Parents are carried over by pygit2, so amending a merge commit keeps
        both sides.
        """
        if self._repo.head_is_unborn:
            raise ValueError("Nothing to amend — this branch has no commits yet.")
        self._repo.index.write()
        tree = self._repo.index.write_tree()
        head = self._repo.head.peel(pygit2.Commit)
        oid = self._repo.amend_commit(
            head,
            "HEAD",
            author=head.author,
            committer=self._get_signature(),
            message=message,
            tree=tree,
        )
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
