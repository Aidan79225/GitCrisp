"""Cancellation of in-flight remote git operations (RemoteOps)."""

from __future__ import annotations

import os
import sys
import threading
import time

import pytest

from git_gui.domain.ports import RemoteOperationCancelled
from git_gui.infrastructure.pygit2 import Pygit2Repository


def test_cancel_when_idle_is_noop(repo_impl):
    """Cancelling with no operation running must not raise."""
    repo_impl.cancel_remote_op()  # no active process → no-op


def test_the_local_git_runner_completes_a_command(repo_impl):
    """The runner a merge or rebase uses, which no cancel can stop."""
    repo_impl._run_git("--version")


def test_a_failed_fetch_raises_runtime_error_not_cancelled(repo_impl):
    """A remote op that fails on its own is not reported as cancelled."""
    with pytest.raises(RuntimeError) as exc:
        repo_impl.fetch("definitely-not-a-remote")
    assert not isinstance(exc.value, RemoteOperationCancelled)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX fake-git shell script")
def test_cancel_terminates_running_git(repo_path, tmp_path, monkeypatch):
    """A long-running git process is killed promptly on cancel, and the fetch
    surfaces RemoteOperationCancelled rather than hanging on the child's pipes."""
    # Fake `git` whose fetch blocks — stands in for a slow fetch/push. The extra
    # `sleep` child mimics git's transport helper, so a plain terminate() of the
    # top process would leave a grandchild holding the pipes open. Any other
    # subcommand (the `git config --get` the adapter runs first, to learn the
    # user's ssh command) returns at once, as real git would.
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text('#!/bin/sh\ncase "$1" in fetch|push|pull) sleep 30 ;; *) exit 1 ;; esac\n')
    fake_git.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + os.environ["PATH"])

    impl = Pygit2Repository(str(repo_path))
    result: dict = {}

    def _run():
        start = time.monotonic()
        try:
            impl.fetch("origin")
        except Exception as e:  # capture whatever it raises
            result["exc"] = e
            result["elapsed"] = time.monotonic() - start

    worker = threading.Thread(target=_run)
    worker.start()

    # Wait until the subprocess is registered, then cancel.
    for _ in range(500):
        with impl._remote_proc_lock:
            if impl._active_remote_proc is not None:
                break
        time.sleep(0.01)
    impl.cancel_remote_op()

    worker.join(timeout=10)
    assert not worker.is_alive(), "cancel did not unblock the worker"
    assert isinstance(result.get("exc"), RemoteOperationCancelled)
    assert result["elapsed"] < 10  # well under the fake 30s sleep


def test_aborting_a_merge_leaves_the_running_fetch_cancellable(repo_impl):
    """A local command run while a fetch is in flight must not take its cancel slot."""
    in_flight_fetch = object()
    repo_impl._active_remote_proc = in_flight_fetch
    with pytest.raises(RuntimeError):
        repo_impl.merge_abort()  # Nothing to abort, but git still runs.
    assert repo_impl._active_remote_proc is in_flight_fetch
