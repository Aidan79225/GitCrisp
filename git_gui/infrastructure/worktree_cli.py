from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Mapping

from git_gui.infrastructure.git_process import run_git


class WorktreeCommandError(Exception):
    """Generic failure from `git worktree ...`."""


class WorktreeDirtyError(WorktreeCommandError):
    """Removal refused because the worktree has uncommitted changes or
    initialised submodules, either of which forcing it would discard."""


class WorktreeLockedError(WorktreeCommandError):
    """Removal refused because the worktree is locked."""


_DIRTY_RE = re.compile(
    r"\b(is dirty|contains modified or untracked files|containing submodules)\b", re.IGNORECASE
)
_LOCKED_RE = re.compile(r"\b(is locked|locked working tree)\b", re.IGNORECASE)


class WorktreeCli:
    """Thin wrapper around `git worktree add` / `remove` executed via subprocess.

    pygit2 lacks a "remove worktree with directory cleanup" call, and its add
    refuses an existing empty folder and a folder name another worktree already
    uses, both of which git accepts, so we shell out to the git CLI. `repo_dir`
    is only the cwd, so worktree paths must be absolute.

    Pass `env` with GIT_DIR to pin git to that repository. Without it git
    finds the repository from `repo_dir`, unless the app inherited a GIT_DIR
    of its own, which git ranks first.
    """

    def __init__(
        self,
        repo_dir: str,
        git_executable: str = "git",
        *,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._cwd = repo_dir
        self._git = git_executable
        self._env = env

    def add(self, worktree_path: str, branch: str) -> None:
        """Check out the existing local `branch` in a new worktree.
        Raises `WorktreeCommandError`."""
        self._run(["worktree", "add", "--", worktree_path, branch])

    def remove(self, worktree_path: str, *, force: bool) -> None:
        """Remove a worktree. Raises `WorktreeDirtyError` /
        `WorktreeLockedError` / `WorktreeCommandError`."""
        args = ["worktree", "remove"]
        if force:
            # Once overrides uncommitted changes; a lock needs it a second time.
            args += ["--force", "--force"]
        try:
            self._run([*args, worktree_path])
        except WorktreeCommandError as e:
            message = str(e)
            if _DIRTY_RE.search(message):
                raise WorktreeDirtyError(message) from e
            if _LOCKED_RE.search(message):
                raise WorktreeLockedError(message) from e
            raise

    def _run(self, args: list[str]) -> None:
        if shutil.which(self._git) is None:
            raise WorktreeCommandError(f"`{self._git}` executable not found on PATH")
        try:
            run_git([self._git, *args], cwd=self._cwd, env=self._env, check=True)
        except subprocess.CalledProcessError as e:
            message = (e.stderr or "").strip() or (e.stdout or "").strip() or str(e)
            raise WorktreeCommandError(message) from e
        except FileNotFoundError as e:
            raise WorktreeCommandError(f"`{self._git}` executable not found on PATH") from e
