"""Cancellation of in-flight remote git operations (RemoteOps)."""

from __future__ import annotations

import os
import sys
import threading
import time

import pytest

from git_gui.infrastructure.pygit2 import Pygit2Repository
from git_gui.infrastructure.pygit2.remote_ops import RemoteOperationCancelled


def test_cancel_when_idle_is_noop(repo_impl):
    """Cancelling with no operation running must not raise."""
    repo_impl.cancel_remote_op()  # no active process → no-op


def test_run_git_success(repo_impl):
    """A normal git invocation still completes cleanly."""
    repo_impl._run_git("--version")


def test_run_git_failure_raises_runtimeerror(repo_impl):
    """A failing remote op raises RuntimeError (not RemoteOperationCancelled)."""
    with pytest.raises(RuntimeError) as exc:
        repo_impl.fetch("definitely-not-a-remote")
    assert not isinstance(exc.value, RemoteOperationCancelled)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX fake-git shell script")
def test_cancel_terminates_running_git(repo_path, tmp_path, monkeypatch):
    """A long-running git process is killed promptly on cancel, and _run_git
    surfaces RemoteOperationCancelled rather than hanging on the child's pipes."""
    # Fake `git` that blocks — stands in for a slow fetch/push. The extra `sleep`
    # child mimics git's transport helper, so a plain terminate() of the top
    # process would leave a grandchild holding the pipes open.
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text("#!/bin/sh\nsleep 30\n")
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
