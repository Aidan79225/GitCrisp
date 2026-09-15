from __future__ import annotations

import logging
import os
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
            # pygit2 ≥ a future version is expected to expose is_locked.
            # Today (1.19.2) the attribute is missing, so we fall back to
            # checking the .git/worktrees/<name>/locked sentinel file.
            try:
                is_locked = wt.is_locked
            except AttributeError:
                is_locked = (common_dir / "worktrees" / name / "locked").exists()
            lock_reason = None
            if is_locked:
                locked_file = common_dir / "worktrees" / name / "locked"
                try:
                    lock_reason = locked_file.read_text().strip() or None
                except OSError:
                    lock_reason = None
            result.append(
                Worktree(
                    path=str(Path(wt.path).resolve()),
                    branch=wt_branch,
                    head_sha=wt_sha,
                    is_locked=bool(is_locked),
                    lock_reason=lock_reason,
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
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        if create_branch:
            base = base_ref or "HEAD"
            try:
                base_obj = self._repo.revparse_single(base)
            except Exception as e:
                raise ValueError(f"Base ref not found: {base}") from e
            self._repo.references.create(f"refs/heads/{branch}", base_obj.id)

        ref = self._repo.references.get(f"refs/heads/{branch}")
        if ref is None:
            raise ValueError(f"Branch not found: {branch}")

        # pygit2's "name" is the dir name under .git/worktrees/<name>/.
        # Use the basename of the target for predictability.
        wt_name = target.name
        self._repo.add_worktree(wt_name, str(target), ref)

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

    def remove_worktree(self, path: str, *, force: bool) -> None:
        from git_gui.infrastructure.worktree_cli import WorktreeCli

        cli = WorktreeCli(self._repo.workdir)
        cli.remove(path, force=force)

    def lock_worktree(self, path: str, *, reason: str | None = None) -> None:
        target = Path(path).resolve()
        name = self._worktree_name_for(target)
        wt = self._repo.lookup_worktree(name)
        # pygit2 ≥ a future version is expected to expose lock(reason). Today
        # (1.19.2) it raises AttributeError; we fall back to writing the
        # `locked` file directly. The reason write below is idempotent in
        # either case — when the API exists it overwrites with the same
        # content; otherwise it provides the persistence.
        locked_file = self._common_dir() / "worktrees" / name / "locked"
        try:
            wt.lock(reason or "")
        except (AttributeError, TypeError):
            locked_file.touch()
        if reason is not None:
            try:
                locked_file.write_text(reason)
            except OSError as e:
                logger.warning("Failed to write lock reason for worktree %r: %s", name, e)

    def unlock_worktree(self, path: str) -> None:
        target = Path(path).resolve()
        name = self._worktree_name_for(target)
        wt = self._repo.lookup_worktree(name)
        try:
            wt.unlock()
        except (AttributeError, TypeError):
            locked = self._common_dir() / "worktrees" / name / "locked"
            if locked.exists():
                locked.unlink()

    # ── Internals ────────────────────────────────────────────────────────

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

    def _worktree_name_for(self, target: Path) -> str:
        for name in self._repo.list_worktrees():
            wt = self._repo.lookup_worktree(name)
            if Path(wt.path).resolve() == target:
                return name
        raise ValueError(f"No worktree at {target}")
