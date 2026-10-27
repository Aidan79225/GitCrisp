"""Pull on a branch that tracks a local branch, against a real repo and git."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from git_gui.infrastructure.pygit2 import Pygit2Repository
from git_gui.presentation.bus import CommandBus, QueryBus
from tests.presentation.window_helpers import blank_window


def _git(cwd, *args) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _clone_with_a_stacked_branch(tmp_path):
    """A clone of a bare origin where the checked-out topic tracks the local
    feature/login, which has moved on by one commit since topic was cut."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "master", str(origin))
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(origin), str(clone))
    _git(clone, "config", "user.email", "t@t")
    _git(clone, "config", "user.name", "t")
    _git(clone, "commit", "-q", "--allow-empty", "-m", "init")
    _git(clone, "push", "-q", "origin", "master")
    _git(clone, "branch", "feature/login")
    _git(clone, "branch", "--track", "topic", "feature/login")
    _git(clone, "checkout", "-q", "feature/login")
    _git(clone, "commit", "-q", "--allow-empty", "-m", "login form")
    _git(clone, "checkout", "-q", "topic")
    return clone


def test_pull_on_a_branch_stacked_on_a_local_branch_brings_in_its_commits(qtbot, tmp_path):
    clone = _clone_with_a_stacked_branch(tmp_path)
    repo = Pygit2Repository(str(clone))
    win = blank_window(qtbot)
    win._queries, win._commands = QueryBus.from_reader(repo), CommandBus.from_writer(repo)

    with patch.object(win, "_reload"):
        win._on_pull()
        qtbot.waitUntil(lambda: not win._remote_running, timeout=10000)

    log = win._log_panel._body.toPlainText()
    assert "ERROR" not in log, log
    assert _git(clone, "rev-parse", "topic") == _git(clone, "rev-parse", "feature/login")
