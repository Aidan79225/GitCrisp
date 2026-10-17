from __future__ import annotations

import os
import shutil
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path

from git_gui.infrastructure.git_process import run_git
from git_gui.resources import git_ssh_env


class SubmoduleCommandError(Exception):
    """Raised when a `git submodule` (or related) CLI call fails."""


class SubmoduleCli:
    """Thin wrapper around `git submodule` operations executed via subprocess.

    pygit2 lacks reliable support for submodule add/remove/url-change, so we
    shell out to the `git` CLI. The repo working directory is used as cwd.
    """

    def __init__(self, repo_workdir: str, git_executable: str = "git") -> None:
        self._cwd = repo_workdir
        self._git = git_executable

    def _run(self, *args: str) -> str:
        if shutil.which(self._git) is None:
            raise SubmoduleCommandError(f"`{self._git}` executable not found on PATH")
        try:
            # Paths come from the repo, not from a user pattern: without this a
            # submodule at "lib[1]" makes `rm -f` also delete a tracked "lib1".
            completed = run_git(
                [self._git, "--literal-pathspecs", *args],
                cwd=self._cwd,
                env=git_ssh_env(),
                check=True,
            )
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip() or (e.stdout or "").strip() or str(e)
            raise SubmoduleCommandError(stderr) from e
        except FileNotFoundError as e:
            raise SubmoduleCommandError(f"`{self._git}` executable not found on PATH") from e
        return completed.stdout

    def add(self, path: str, url: str) -> None:
        self._run("submodule", "add", "--", url, path)
        # Explicitly re-init after add. `git submodule add` normally leaves
        # the submodule in a fully-initialized state (workdir populated,
        # .git gitlink file written), but in practice we have seen broken
        # states where the .git gitlink was missing. `update --init` is a
        # no-op when everything is already correct, so it is safe to run
        # unconditionally and ensures the submodule is usable afterwards.
        self._run("submodule", "update", "--init", "--", path)

    def set_url(self, path: str, url: str) -> None:
        # .gitmodules sections are keyed by submodule name, which differs from
        # the path after `add --name` or `git mv`; set-url resolves it and syncs.
        self._run("submodule", "set-url", "--", path, url)

    def remove(self, path: str) -> None:
        # Resolved first: `git rm` drops the .gitmodules entry that names it.
        gitdir = self._module_gitdir(path)
        self._run("submodule", "deinit", "-f", "--", path)
        self._run("rm", "-f", "--", path)
        if gitdir is not None and gitdir.exists():
            _delete_module_gitdir(path, gitdir)

    def _module_gitdir(self, path: str) -> Path | None:
        """The submodule's repository, at modules/<name> in this worktree's git dir."""
        output = self._run(
            "rev-parse", "--git-path", "modules", "--git-path", f"modules/{self._name_of(path)}"
        )
        modules_root, gitdir = (Path(self._cwd, line).resolve() for line in output.splitlines())
        # A hand-written .gitmodules can name a submodule "../.."; never
        # delete anything outside modules/.
        return gitdir if modules_root in gitdir.parents else None

    def _name_of(self, path: str) -> str:
        try:
            listing = self._run(
                "config", "-f", ".gitmodules", "--null", "--get-regexp", r"^submodule\..*\.path$"
            )
        except SubmoduleCommandError:
            # --get-regexp fails when nothing matches; git's default name is the path.
            return path
        for record in listing.split("\0"):
            key, _, value = record.partition("\n")
            if value == path:
                return key.removeprefix("submodule.").removesuffix(".path")
        return path


def _delete_module_gitdir(path: str, gitdir: Path) -> None:
    try:
        shutil.rmtree(gitdir, onexc=_make_writable_and_retry)
    except OSError as e:
        raise SubmoduleCommandError(
            f"Removed submodule '{path}', but could not delete its repository at {gitdir}: {e}"
        ) from e


def _make_writable_and_retry(func: Callable[[str], object], path: str, _exc: BaseException) -> None:
    # git writes object and pack files read-only, and Windows refuses to
    # delete a read-only file.
    os.chmod(path, stat.S_IWRITE)
    func(path)
