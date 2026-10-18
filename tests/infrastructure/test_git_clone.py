"""clone_repo: the Clone dialog's git clone runner."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from git_gui.infrastructure import git_clone
from git_gui.infrastructure.git_clone import CloneCancelled, clone_repo

# A recursive clone prints one "Submodule path ...: checked out ..." line per
# submodule to stdout; this is far more than any OS pipe buffer holds.
_CHATTY_STDOUT_GIT = (
    "import sys\n"
    "sys.stdout.write(\"Submodule path 'lib': checked out 'abc'\\n\" * 8000)\n"
    "sys.stdout.flush()\n"
)


@pytest.fixture
def fake_git(monkeypatch):
    """Run a Python script in place of git, keeping clone_repo's pipe setup."""
    started: list[subprocess.Popen] = []
    real_popen = subprocess.Popen

    def use(script: str) -> None:
        def popen(args, **kwargs):
            proc = real_popen([sys.executable, "-c", script], **kwargs)
            started.append(proc)
            return proc

        monkeypatch.setattr(git_clone.subprocess, "Popen", popen)

    yield use
    for proc in started:
        proc.kill()


def test_a_clone_that_prints_a_lot_to_stdout_still_finishes(fake_git):
    fake_git(_CHATTY_STDOUT_GIT)
    worker = threading.Thread(target=clone_repo, args=("url", "dest"), daemon=True)
    worker.start()
    worker.join(timeout=20)
    assert not worker.is_alive(), "clone_repo blocked on git's unread stdout"


def test_a_failed_clone_reports_why_git_refused(repo_path, tmp_path):
    dest = tmp_path / "taken"
    dest.mkdir()
    (dest / "file.txt").write_text("already here")
    with pytest.raises(Exception) as excinfo:
        clone_repo(str(repo_path), str(dest))
    assert "already exists and is not an empty directory" in str(excinfo.value)


def _git_writing_stderr(text: str, exit_code: int = 0) -> str:
    return f"import sys\nsys.stderr.write({text!r})\nsys.exit({exit_code})\n"


def test_the_failure_message_keeps_a_last_line_without_a_newline(fake_git):
    fake_git(_git_writing_stderr("Receiving objects:  50% (1/2)\rfatal: boom", exit_code=128))
    with pytest.raises(Exception) as excinfo:
        clone_repo("url", "dest")
    assert str(excinfo.value) == "fatal: boom"


def test_progress_lines_reach_the_callback(fake_git):
    fake_git(
        _git_writing_stderr("Receiving objects:  50% (1/2)\rReceiving objects: 100% (2/2), done.\n")
    )
    seen: list[tuple[str, int]] = []
    clone_repo("url", "dest", on_progress=lambda p: seen.append((p.phase, p.percent)))
    assert seen == [("Receiving objects", 50), ("Receiving objects", 100)]


@pytest.mark.skipif(os.name != "posix", reason="sessions and controlling terminals are POSIX")
def test_a_clone_runs_without_the_terminal_the_app_was_started_from(fake_git):
    """ssh would ask that terminal for a passphrase while the dialog waits."""
    fake_git("import os, sys\nsys.stderr.write(str(os.getsid(0)))\nsys.exit(128)\n")
    with pytest.raises(RuntimeError) as excinfo:
        clone_repo("url", "dest")
    assert int(str(excinfo.value)) != os.getsid(0)


def test_a_clone_into_an_empty_folder_fills_that_folder(repo_path, tmp_path):
    dest = tmp_path / "empty"
    dest.mkdir()
    clone_repo(str(repo_path), str(dest))
    assert (dest / ".git").is_dir()


def test_a_failed_clone_leaves_no_folder_behind(tmp_path):
    dest = tmp_path / "new"
    with pytest.raises(RuntimeError):
        clone_repo(str(tmp_path / "no-such-repo"), str(dest))
    assert not dest.exists()


# The hook stands in for a remote that stops sending mid-clone. It runs a few
# processes below git (upload-pack, pack-objects, sh), as a real clone runs
# ssh or git-remote-https, and those keep git's stderr open while they live.
_SLOW_PACK_OBJECTS_HOOK = '#!/bin/sh\n: > "{started}"\nsleep 60\nexec "$@"\n'
# Without keepalives upload-pack stays silent, as a dropped connection does,
# instead of finding out from a failed write that git is gone.
_STALLED_REMOTE_CONFIG = "[uploadpack]\n\tpackObjectsHook = {hook}\n\tkeepAlive = 0\n"


class _BackgroundClone:
    def __init__(self, url: str, dest: Path) -> None:
        self.cancel = threading.Event()
        self.error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, args=(url, str(dest)), daemon=True)
        self._thread.start()

    def _run(self, url: str, dest: str) -> None:
        try:
            clone_repo(url, dest, cancelled=self.cancel)
        except BaseException as error:
            self.error = error

    def finished_within(self, seconds: float) -> bool:
        self._thread.join(seconds)
        return not self._thread.is_alive()


@pytest.fixture
def stalled_clone(repo_path, tmp_path_factory, monkeypatch):
    """Start a clone of repo_path into a destination; it stalls until cancelled."""
    work = tmp_path_factory.mktemp("stalled-clone")
    started = work / "hook-started"
    hook = work / "slow-pack-objects"
    hook.write_text(_SLOW_PACK_OBJECTS_HOOK.format(started=started.as_posix()), newline="\n")
    hook.chmod(0o755)
    config = work / "gitconfig"
    config.write_text(_STALLED_REMOTE_CONFIG.format(hook=hook.as_posix()))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))

    def start(dest: Path) -> _BackgroundClone:
        clone = _BackgroundClone(repo_path.as_uri(), dest)
        deadline = time.monotonic() + 30
        while not started.exists():
            assert time.monotonic() < deadline, f"the clone never reached the remote: {clone.error}"
            time.sleep(0.05)
        return clone

    return start, work


def _cancel(clone: _BackgroundClone) -> None:
    clone.cancel.set()
    assert clone.finished_within(20), "git kept running after the clone was cancelled"


def test_cancelling_a_stalled_clone_stops_git(stalled_clone):
    start, work = stalled_clone
    clone = start(work / "repo")
    _cancel(clone)
    assert isinstance(clone.error, CloneCancelled)


def test_a_cancelled_clone_removes_the_folder_it_created(stalled_clone):
    start, work = stalled_clone
    dest = work / "repo"
    _cancel(start(dest))
    assert not dest.exists()


def test_a_cancelled_clone_keeps_the_empty_folder_it_was_given(stalled_clone):
    start, work = stalled_clone
    dest = work / "repo"
    dest.mkdir()
    _cancel(start(dest))
    assert dest.is_dir() and list(dest.iterdir()) == []
