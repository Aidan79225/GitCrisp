"""clone_repo: the Clone dialog's git clone runner."""

from __future__ import annotations

import os
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
