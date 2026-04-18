from __future__ import annotations
import subprocess

import pygit2

from git_gui.resources import subprocess_kwargs
from git_gui.domain.entities import Remote


class RemoteOps:
    """Remote management + subprocess-based git push/pull/fetch.

    Mixin — not instantiable on its own. Relies on `self._repo` and
    `self._git_env` set up by the composite class.
    """
    _repo: pygit2.Repository  # provided by the composite

    # ── METHODS COPIED VERBATIM from Pygit2Repository ─────────────────
    def push(self, remote: str, branch: str) -> None:
        self._run_git("push", remote, branch)

    def force_push(self, remote: str, branch: str) -> None:
        self._run_git("push", "--force-with-lease", remote, branch)

    def pull(self, remote: str, branch: str) -> None:
        self._run_git("pull", "--rebase", remote, branch)

    def fetch(self, remote: str) -> None:
        self._run_git("fetch", remote)

    def fetch_all_prune(self) -> None:
        self._run_git("fetch", "--all", "--prune")

    def _run_git(self, *args: str) -> None:
        result = subprocess.run(
            ["git", *args],
            cwd=self._repo.workdir, capture_output=True, text=True,
            env=self._git_env, **subprocess_kwargs(),
        )
        if result.returncode != 0:
            msg = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
            raise RuntimeError(msg)

    # ----- Remotes -----

    def list_remotes(self) -> list[Remote]:
        result: list[Remote] = []
        for r in self._repo.remotes:
            push_url = r.push_url if r.push_url else r.url
            result.append(Remote(name=r.name, fetch_url=r.url, push_url=push_url))
        return result

    def add_remote(self, name: str, url: str) -> None:
        self._repo.remotes.create(name, url)

    def remove_remote(self, name: str) -> None:
        self._repo.remotes.delete(name)

    def rename_remote(self, old_name: str, new_name: str) -> None:
        self._repo.remotes.rename(old_name, new_name)

    def set_remote_url(self, name: str, url: str) -> None:
        self._repo.remotes.set_url(name, url)
