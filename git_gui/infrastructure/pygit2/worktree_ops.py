from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext, suppress
from pathlib import Path

import pygit2

from git_gui.domain.entities import Worktree

logger = logging.getLogger(__name__)


def _read_head_branch(workdir: str) -> tuple[str | None, str]:
    """Return (branch_name_or_None, head_sha) for a worktree at *workdir*.

    Reads `.git` (a file in linked worktrees, a dir in the main worktree)
    and resolves HEAD. Detached → branch is None and sha is the raw oid.
    """
    repo = pygit2.Repository(workdir)
    try:
        head = repo.head
    except pygit2.GitError:
        return None, ""
    if repo.head_is_detached:
        return None, str(head.target)
    return head.shorthand, str(head.target)


def _read_lock_reason(lock_file: Path) -> str | None:
    try:
        reason = lock_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return reason.strip() or None


class WorktreeOps:
    """Worktree read/write operations.

    Mixin — not instantiable on its own. Relies on `self._repo` set up
    by the composite class.
    """

    _repo: pygit2.Repository  # provided by the composite

    # ── Reads ────────────────────────────────────────────────────────────

    def list_worktrees(self) -> list[Worktree]:
        result: list[Worktree] = []
        common_dir = self._common_dir()

        # Main worktree — read from the common git dir, not from this session:
        # a session opened on a linked worktree has that worktree as its own
        # workdir, and taking it for the main one loses the real main repo.
        common = pygit2.Repository(str(common_dir))
        main_workdir = common.workdir or ""
        if main_workdir:
            main_branch, main_sha = _read_head_branch(main_workdir)
            result.append(
                Worktree(
                    path=str(Path(main_workdir).resolve()),
                    branch=main_branch,
                    head_sha=main_sha,
                    is_locked=False,
                    lock_reason=None,
                    is_bare=common.is_bare,
                    is_main=True,
                )
            )

        # Linked worktrees.
        try:
            names = list(self._repo.list_worktrees())
        except Exception as e:
            logger.warning("Failed to list linked worktrees: %s", e)
            names = []
        for name in names:
            try:
                wt = self._repo.lookup_worktree(name)
            except Exception as e:
                logger.warning("Failed to look up worktree %r: %s", name, e)
                continue
            try:
                wt_branch, wt_sha = _read_head_branch(wt.path)
            except Exception as e:
                logger.warning("Failed to read HEAD for worktree %r: %s", name, e)
                wt_branch, wt_sha = None, ""
            lock_file = self._lock_file(name)
            is_locked = lock_file.exists()
            result.append(
                Worktree(
                    path=str(Path(wt.path).resolve()),
                    branch=wt_branch,
                    head_sha=wt_sha,
                    is_locked=is_locked,
                    lock_reason=_read_lock_reason(lock_file) if is_locked else None,
                    is_bare=False,
                    is_main=False,
                )
            )
        return result

    def find_worktree_for_branch(self, branch: str) -> Worktree | None:
        for wt in self.list_worktrees():
            if wt.branch == branch:
                return wt
        return None

    # ── Writes ───────────────────────────────────────────────────────────

    def add_worktree(
        self,
        path: str,
        branch: str,
        *,
        create_branch: bool,
        base_ref: str | None,
    ) -> Worktree:
        target = Path(path).absolute()

        if create_branch:
            base = base_ref or "HEAD"
            try:
                base_commit = self._base_commit(base)
            except Exception as e:
                raise ValueError(f"Base ref not found: {base}") from e
            self._repo.references.create(f"refs/heads/{branch}", base_commit.id)

        if self._repo.references.get(f"refs/heads/{branch}") is None:
            raise ValueError(f"Branch not found: {branch}")

        try:
            self._worktree_cli().add(str(target), branch)
        except Exception:
            # A branch left behind would make retrying the same name fail, but
            # git keeps the worktree when only its post-checkout hook failed.
            if create_branch and self.find_worktree_for_branch(branch) is None:
                self._repo.references.delete(f"refs/heads/{branch}")
            raise

        wt_branch, wt_sha = _read_head_branch(str(target))
        return Worktree(
            path=str(target.resolve()),
            branch=wt_branch,
            head_sha=wt_sha,
            is_locked=False,
            lock_reason=None,
            is_bare=False,
            is_main=False,
        )

    def remove_worktree(self, path: str, *, force: bool, override_lock: bool = False) -> None:
        lock = self._lock_lifted(path) if override_lock else nullcontext()
        with lock:
            self._worktree_cli().remove(path, force=force)

    def lock_worktree(self, path: str, *, reason: str | None = None) -> None:
        name = self._worktree_name_for(path)
        lock_file = self._lock_file(name)
        lock_file.touch()
        if reason is None:
            return
        try:
            lock_file.write_text(reason, encoding="utf-8")
        except OSError as e:
            logger.warning("Failed to write lock reason for worktree %r: %s", name, e)

    def unlock_worktree(self, path: str) -> None:
        self._lock_file(self._worktree_name_for(path)).unlink(missing_ok=True)

    # ── Internals ────────────────────────────────────────────────────────

    def _worktree_cli(self):
        from git_gui.infrastructure.worktree_cli import WorktreeCli

        # Not the session's workdir: that may be the worktree being removed,
        # and Windows will not delete a process's current directory.
        return WorktreeCli(str(self._common_dir()), env=self._git_env)

    @contextmanager
    def _lock_lifted(self, path: str) -> Iterator[None]:
        """Take the lock off for the block and put it back if the block fails.

        git has no way to override a lock and still refuse uncommitted changes:
        `--force` twice skips both checks. git deletes the admin dir even when
        some files would not go, and then there is no lock left to restore.
        """
        lock_file = self._lock_file(self._worktree_name_for(path))
        try:
            reason = lock_file.read_bytes()
        except FileNotFoundError:
            yield
            return
        lock_file.unlink()
        try:
            yield
        except Exception:
            with suppress(FileNotFoundError):
                lock_file.write_bytes(reason)
            raise

    def _lock_file(self, name: str) -> Path:
        """pygit2's Worktree has no lock API, so locks are git's sentinel file."""
        return self._common_dir() / "worktrees" / name / "locked"

    def _base_commit(self, base: str) -> pygit2.Commit:
        # The dialog offers local branch names, and revparse's DWIM order
        # would take a tag of the same name first.
        branch_ref = f"refs/heads/{base}"
        if pygit2.reference_is_valid_name(branch_ref) and branch_ref in self._repo.references:
            return self._repo.references[branch_ref].peel(pygit2.Commit)
        return self._repo.revparse_single(base).peel(pygit2.Commit)

    def _common_dir(self) -> Path:
        """The git dir every worktree of this repository shares.

        In the main worktree that is the session's own git dir. A session opened
        on a linked worktree has a per-worktree git dir instead, whose
        `commondir` file names the shared one — where `worktrees/` and the lock
        sentinels live.
        """
        git_dir = Path(self._repo.path)
        commondir = git_dir / "commondir"
        if not commondir.is_file():
            return git_dir
        raw = commondir.read_text(encoding="utf-8").strip()
        return Path(os.path.normpath(git_dir / raw)) if raw else git_dir

    def _worktree_name_for(self, path: str) -> str:
        target = Path(path).resolve()
        for name in self._repo.list_worktrees():
            wt = self._repo.lookup_worktree(name)
            if Path(wt.path).resolve() == target:
                return name
        raise ValueError(f"No worktree at {target}")
