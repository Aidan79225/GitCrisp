from __future__ import annotations

import subprocess

import pygit2

from git_gui.domain.entities import Remote, RemoteBranchDeleteResult
from git_gui.domain.ports import RemoteOperationCancelled
from git_gui.infrastructure.git_process import git_popen_kwargs, kill_git_tree, run_git


def _raise_if_git_failed(returncode: int, stdout: str, stderr: str) -> None:
    if returncode != 0:
        raise RuntimeError(stderr.strip() or stdout.strip() or f"exit code {returncode}")


def _parse_porcelain_delete(
    remote: str, stdout: str, branches: list[str]
) -> list[RemoteBranchDeleteResult]:
    """Parse `git push --porcelain ... --delete` output into per-branch results.

    For a delete refspec the source (`<from>`) is always empty because there is
    no source object; the branch being deleted is always in `<to>`.  The line
    format is therefore `<flag>\\t:<to>\\t<summary>` for both successes and
    rejections.  Flag "-" means successfully deleted; "!" means rejected
    (summary carries the reason).  A real rejection looks like:
        ``!\\t:refs/heads/protected\\t[remote rejected] (protected branch)``
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

        # For delete refspecs <from> is always empty; the branch is always in <to>.
        # Falling back to _from is harmless robustness for non-standard git output.
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

    def push(self, remote: str, branch: str) -> None:
        self._run_cancellable_remote_git("push", remote, branch)

    def force_push(self, remote: str, branch: str) -> None:
        self._run_cancellable_remote_git("push", "--force-with-lease", remote, branch)

    def pull(self, remote: str, branch: str) -> None:
        self._run_cancellable_remote_git("pull", "--rebase", remote, branch)

    def fetch(self, remote: str) -> None:
        self._run_cancellable_remote_git("fetch", remote)

    def fetch_all_prune(self) -> None:
        self._run_cancellable_remote_git("fetch", "--all", "--prune")

    def delete_remote_branches(
        self, remote: str, branches: list[str]
    ) -> list[RemoteBranchDeleteResult]:
        if not branches:
            return []
        refspecs = [f"refs/heads/{b}" for b in branches]
        result = run_git(
            ["git", "push", "--porcelain", remote, "--delete", *refspecs],
            cwd=self._repo.workdir,
            env=self._git_env,
        )
        # No per-ref status at all (e.g. couldn't reach the remote): surface stderr.
        if result.returncode != 0 and not result.stdout.strip():
            err = result.stderr.strip() or f"git exited {result.returncode}"
            return [
                RemoteBranchDeleteResult(branch=f"{remote}/{b}", ok=False, message=err)
                for b in branches
            ]
        return _parse_porcelain_delete(remote, result.stdout, branches)

    def _run_git(self, *args: str) -> None:
        """Run a local git command, such as a merge or rebase, to completion.

        It stays out of the remote-op slot: started while a fetch is in flight,
        it would otherwise take that fetch's place, and Cancel would stop the
        wrong process or none.
        """
        result = run_git(["git", *args], cwd=self._repo.workdir, env=self._git_env)
        _raise_if_git_failed(result.returncode, result.stdout, result.stderr)

    def _run_cancellable_remote_git(self, *args: str) -> None:
        """Run a push, pull or fetch as the one remote op `cancel_remote_op` can stop."""
        # Popen (not subprocess.run) so cancel_remote_op can terminate the
        # process mid-transfer. The active handle is published under a lock so
        # the UI thread can reach it while this worker thread blocks on
        # communicate().
        with self._remote_proc_lock:
            self._remote_cancel_requested = False
            proc = subprocess.Popen(
                ["git", *args],
                cwd=self._repo.workdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                # git prints ref names and messages as UTF-8 whatever the
                # locale's code page.
                encoding="utf-8",
                errors="replace",
                env=self._git_env,
                # Its own session, so a cancel reaches the helpers holding the pipes.
                **git_popen_kwargs(),
            )
            self._active_remote_proc = proc
        try:
            stdout, stderr = proc.communicate()
        finally:
            with self._remote_proc_lock:
                cancelled = self._remote_cancel_requested
                self._active_remote_proc = None
                self._remote_cancel_requested = False
        if cancelled:
            raise RemoteOperationCancelled("Operation cancelled")
        _raise_if_git_failed(proc.returncode, stdout, stderr)

    def cancel_remote_op(self) -> None:
        """Terminate the in-flight git push/pull/fetch subprocess, if any.

        Safe to call from any thread (the UI thread calls this while the worker
        thread is blocked in `_run_cancellable_remote_git`). A no-op when
        nothing is running.
        """
        with self._remote_proc_lock:
            proc = self._active_remote_proc
            if proc is None:
                return
            self._remote_cancel_requested = True
        # Kill outside the lock — a syscall shouldn't block the worker thread's
        # teardown path, which also needs the lock.
        kill_git_tree(proc)

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
