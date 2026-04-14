from __future__ import annotations
import os
import shutil
import subprocess
from pathlib import Path

from git_gui.resources import subprocess_kwargs


class CommitOpsCommandError(Exception):
    """Raised when a git cherry-pick / revert CLI call fails unexpectedly."""


class CommitOpsCli:
    """Thin wrapper around `git cherry-pick` and `git revert` via subprocess.

    pygit2 does not accept a mainline (`-m`) argument for cherry-picking or
    reverting a merge commit, so we shell out to the `git` CLI. Conflict exits
    are swallowed: the repo is left in CHERRY_PICK_HEAD / REVERT_HEAD state
    and the caller surfaces the banner on the next reload.
    """

    def __init__(self, repo_workdir: str, git_executable: str = "git") -> None:
        self._cwd = repo_workdir
        self._git = git_executable

    def cherry_pick(self, oid: str, is_merge: bool) -> None:
        argv = ["cherry-pick"]
        if is_merge:
            argv += ["-m", "1"]
        argv.append(oid)
        self._run(argv, conflict_state_file="CHERRY_PICK_HEAD")

    def revert_commit(self, oid: str, is_merge: bool) -> None:
        argv = ["revert", "--no-edit"]
        if is_merge:
            argv += ["-m", "1"]
        argv.append(oid)
        self._run(argv, conflict_state_file="REVERT_HEAD")

    def cherry_pick_abort(self) -> None:
        self._run(["cherry-pick", "--abort"])

    def cherry_pick_continue(self) -> None:
        self._run(["cherry-pick", "--continue"], env_overrides={"GIT_EDITOR": "true"})

    def revert_abort(self) -> None:
        self._run(["revert", "--abort"])

    def revert_continue(self) -> None:
        self._run(["revert", "--continue"], env_overrides={"GIT_EDITOR": "true"})

    def _run(
        self,
        argv: list[str],
        env_overrides: dict[str, str] | None = None,
        conflict_state_file: str | None = None,
    ) -> None:
        if shutil.which(self._git) is None:
            raise CommitOpsCommandError(f"`{self._git}` executable not found on PATH")
        env = os.environ.copy()
        if env_overrides:
            env.update(env_overrides)
        try:
            result = subprocess.run(
                [self._git, *argv],
                cwd=self._cwd,
                capture_output=True,
                text=True,
                env=env,
                **subprocess_kwargs(),
            )
        except FileNotFoundError as e:
            raise CommitOpsCommandError(
                f"`{self._git}` executable not found on PATH"
            ) from e
        if result.returncode == 0:
            return
        if conflict_state_file is not None and (
            Path(self._cwd) / ".git" / conflict_state_file
        ).exists():
            return
        stderr = (result.stderr or "").strip() or (result.stdout or "").strip() or f"exit code {result.returncode}"
        raise RuntimeError(stderr)
