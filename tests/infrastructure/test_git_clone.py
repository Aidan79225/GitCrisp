"""clone_repo: the Clone dialog's git clone runner."""

from __future__ import annotations

import subprocess
import sys
import threading

import pytest

from git_gui.infrastructure import git_clone
from git_gui.infrastructure.git_clone import clone_repo

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
