from __future__ import annotations

import shutil
from pathlib import Path

from git_gui.infrastructure.git_process import git_run_dir, pinned_git_env, run_git


class CommitOpsCommandError(Exception):
    """Raised when a git cherry-pick / revert CLI call fails unexpectedly."""


class CommitOpsCli:
    """Thin wrapper around `git cherry-pick` and `git revert` via subprocess.

    pygit2 does not accept a mainline (`-m`) argument for cherry-picking or
    reverting a merge commit, so we shell out to the `git` CLI. Conflict exits
    are swallowed: the repo is left in CHERRY_PICK_HEAD / REVERT_HEAD state
    and the caller surfaces the banner on the next reload.

    Pass `git_dir` to pin git to that repository. Without it git discovers
    the repository from `repo_workdir`, which for a submodule whose `.git`
    link is missing walks up to the parent and runs against the wrong repo.
    """

    def __init__(
        self, repo_workdir: str | None, git_executable: str = "git", *, git_dir: str | None = None
    ) -> None:
        self._cwd = git_run_dir(repo_workdir, git_dir)
        self._work_tree = repo_workdir
        self._git = git_executable
        self._git_dir = git_dir

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
        try:
            result = run_git([self._git, *argv], cwd=self._cwd, env=self._env(env_overrides))
        except FileNotFoundError as e:
            raise CommitOpsCommandError(f"`{self._git}` executable not found on PATH") from e
        if result.returncode == 0:
            return
        if conflict_state_file is not None and (self._state_dir() / conflict_state_file).exists():
            return
        stderr = (
            (result.stderr or "").strip()
            or (result.stdout or "").strip()
            or f"exit code {result.returncode}"
        )
        raise RuntimeError(stderr)

    def _env(self, overrides: dict[str, str] | None) -> dict[str, str]:
        env = pinned_git_env(self._git_dir, self._work_tree)
        env.update(overrides or {})
        return env

    def _state_dir(self) -> Path:
        # In a linked worktree or a submodule `<workdir>/.git` is a file, and
        # git writes CHERRY_PICK_HEAD / REVERT_HEAD into the gitdir it names.
        if self._git_dir is not None:
            return Path(self._git_dir)
        return Path(self._cwd) / ".git"
