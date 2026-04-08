from __future__ import annotations
import shutil
import subprocess
from pathlib import Path

from git_gui.resources import subprocess_kwargs


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

    def _run(self, *args: str) -> None:
        if shutil.which(self._git) is None:
            raise SubmoduleCommandError(
                f"`{self._git}` executable not found on PATH"
            )
        try:
            subprocess.run(
                [self._git, *args],
                cwd=self._cwd,
                check=True,
                capture_output=True,
                text=True,
                **subprocess_kwargs(),
            )
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip() or (e.stdout or "").strip() or str(e)
            raise SubmoduleCommandError(stderr) from e
        except FileNotFoundError as e:
            raise SubmoduleCommandError(
                f"`{self._git}` executable not found on PATH"
            ) from e

    def add(self, path: str, url: str) -> None:
        # -c protocol.file.allow=always is required for local file:// URLs
        # (git ≥ 2.38.1 blocks file transport by default; we restore the
        # pre-CVE-2022-39253 behaviour only for the explicit submodule-add
        # operation where the caller has already decided to add the repo).
        self._run(
            "-c", "protocol.file.allow=always",
            "submodule", "add", "--", url, path,
        )

    def set_url(self, path: str, url: str) -> None:
        self._run("config", "-f", ".gitmodules", f"submodule.{path}.url", url)
        self._run("submodule", "sync", "--", path)

    def remove(self, path: str) -> None:
        self._run("submodule", "deinit", "-f", "--", path)
        self._run("rm", "-f", "--", path)
        modules_dir = Path(self._cwd) / ".git" / "modules" / path
        if modules_dir.exists():
            shutil.rmtree(modules_dir, ignore_errors=True)
