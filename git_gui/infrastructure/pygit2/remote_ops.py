from __future__ import annotations

import subprocess

import pygit2

from git_gui.domain.entities import Remote, RemoteBranchDeleteResult
from git_gui.resources import subprocess_kwargs


def _parse_porcelain_delete(
    remote: str, stdout: str, branches: list[str]
) -> list[RemoteBranchDeleteResult]:
    """Parse `git push --porcelain ... --delete` output into per-branch results.

    Porcelain ref lines are tab-separated: `<flag>\\t<from>:<to>\\t<summary>`.
    For a delete the `<to>` ref identifies the branch; flag "-" means deleted,
    "!" means rejected (summary carries the reason).
    """
    status: dict[str, tuple[bool, str]] = {}
    for line in stdout.splitlines():
        if "\t" not in line:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        flag, refpair, summary = parts[0], parts[1], parts[2]
        if ":" not in refpair:
            continue
        _from, to_ref = refpair.split(":", 1)
        _from = _from.strip()
        to_ref = to_ref.strip()

        # For successful deletes, the branch ref is in the "to" part (empty means deleted from remote)
        # For rejected deletes, the branch ref is in the "from" part
        ref = to_ref or _from
        if not ref:
            continue

        short = ref
        if short.startswith("refs/heads/"):
            short = short[len("refs/heads/") :]
        ok = flag.strip() == "-"
        status[short] = (ok, "deleted" if ok else summary.strip())

    results: list[RemoteBranchDeleteResult] = []
    for b in branches:
        ok, msg = status.get(b, (False, "no result reported by git"))
        results.append(RemoteBranchDeleteResult(branch=f"{remote}/{b}", ok=ok, message=msg))
    return results


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
            cwd=self._repo.workdir,
            capture_output=True,
            text=True,
            env=self._git_env,
            **subprocess_kwargs(),
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
