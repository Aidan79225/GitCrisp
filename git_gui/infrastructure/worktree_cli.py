from __future__ import annotations
import re
import shutil
import subprocess

from git_gui.resources import subprocess_kwargs


class WorktreeCommandError(Exception):
    """Generic failure from `git worktree ...`."""


class WorktreeDirtyError(WorktreeCommandError):
    """Removal refused because the worktree has uncommitted changes."""


class WorktreeLockedError(WorktreeCommandError):
    """Removal refused because the worktree is locked."""


_DIRTY_RE = re.compile(r"\b(is dirty|contains modified or untracked files)\b", re.IGNORECASE)
_LOCKED_RE = re.compile(r"\b(is locked|locked working tree)\b", re.IGNORECASE)


class WorktreeCli:
    """Thin wrapper around `git worktree remove` executed via subprocess.

    pygit2 lacks a "remove worktree with directory cleanup" call, so we
    shell out to the git CLI. The repo's main working directory is used
    as cwd so relative-path resolution matches the user's invocation.
    """

    def __init__(self, repo_workdir: str, git_executable: str = "git") -> None:
        self._cwd = repo_workdir
        self._git = git_executable

    def remove(self, worktree_path: str, *, force: bool) -> None:
        """Remove a worktree. Raises `WorktreeDirtyError` /
        `WorktreeLockedError` / `WorktreeCommandError`."""
        if shutil.which(self._git) is None:
            raise WorktreeCommandError(
                f"`{self._git}` executable not found on PATH"
            )
        args = [self._git, "worktree", "remove"]
        if force:
            args.append("--force")
        args.append(worktree_path)
        try:
            subprocess.run(
                args,
                cwd=self._cwd,
                check=True,
                capture_output=True,
                text=True,
                **subprocess_kwargs(),
            )
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip() or (e.stdout or "").strip() or str(e)
            if _DIRTY_RE.search(stderr):
                raise WorktreeDirtyError(stderr) from e
            if _LOCKED_RE.search(stderr):
                raise WorktreeLockedError(stderr) from e
            raise WorktreeCommandError(stderr) from e
        except FileNotFoundError as e:
            raise WorktreeCommandError(
                f"`{self._git}` executable not found on PATH"
            ) from e
