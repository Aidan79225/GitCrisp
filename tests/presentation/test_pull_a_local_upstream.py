"""Pull on a branch whose upstream is, or shares its name with, a local
branch, against a real repo and git."""

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


def _clone(tmp_path, origin, name):
    clone = tmp_path / name
    _git(tmp_path, "clone", "-q", str(origin), str(clone))
    _git(clone, "config", "user.email", "t@t")
    _git(clone, "config", "user.name", "t")
    return clone


def _clone_with_a_stacked_branch(tmp_path):
    """A clone of a bare origin where the checked-out topic tracks the local
    feature/login, which has moved on by one commit since topic was cut."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "master", str(origin))
    clone = _clone(tmp_path, origin, "clone")
    _git(clone, "commit", "-q", "--allow-empty", "-m", "init")
    _git(clone, "push", "-q", "origin", "master")
    _git(clone, "branch", "feature/login")
    _git(clone, "branch", "--track", "topic", "feature/login")
    _git(clone, "checkout", "-q", "feature/login")
    _git(clone, "commit", "-q", "--allow-empty", "-m", "login form")
    _git(clone, "checkout", "-q", "topic")
    return clone


def _clone_beside_a_local_origin_main(tmp_path):
    """A clone whose checked-out main tracks origin's main, and which also
    holds a local branch named "origin/main", one commit ahead of main: two
    branches that one shorthand names. A teammate has since pushed a commit
    to origin's main; returns the clone and that commit."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    clone = _clone(tmp_path, origin, "clone")
    _git(clone, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(clone, "commit", "-q", "--allow-empty", "-m", "init")
    _git(clone, "push", "-q", "-u", "origin", "main")
    _git(clone, "checkout", "-q", "-b", "origin/main")
    _git(clone, "commit", "-q", "--allow-empty", "-m", "local work")
    _git(clone, "checkout", "-q", "main")
    teammate = _clone(tmp_path, origin, "teammate")
    _git(teammate, "commit", "-q", "--allow-empty", "-m", "teammate's work")
    _git(teammate, "push", "-q", "origin", "main")
    return clone, _git(teammate, "rev-parse", "HEAD")


def _pull_in(qtbot, clone) -> str:
    """Pull the checked-out branch through the window; returns the log."""
    repo = Pygit2Repository(str(clone))
    win = blank_window(qtbot)
    win._queries, win._commands = QueryBus.from_reader(repo), CommandBus.from_writer(repo)

    with patch.object(win, "_reload"):
        win._on_pull()
        qtbot.waitUntil(lambda: not win._remote_running, timeout=10000)

    log = win._log_panel._body.toPlainText()
    assert "ERROR" not in log, log
    return log


def test_pull_on_a_branch_stacked_on_a_local_branch_brings_in_its_commits(qtbot, tmp_path):
    clone = _clone_with_a_stacked_branch(tmp_path)

    _pull_in(qtbot, clone)

    assert _git(clone, "rev-parse", "topic") == _git(clone, "rev-parse", "feature/login")


def test_pull_fetches_from_the_remote_a_branch_tracks_beside_a_local_namesake(qtbot, tmp_path):
    clone, pushed = _clone_beside_a_local_origin_main(tmp_path)

    log = _pull_in(qtbot, clone)

    assert _git(clone, "rev-parse", "main") == pushed
    assert "Pull origin/main — done" in log


def test_pull_stays_in_this_repo_for_a_branch_tracking_the_local_namesake(qtbot, tmp_path):
    clone, pushed = _clone_beside_a_local_origin_main(tmp_path)
    _git(clone, "checkout", "-q", "-b", "topic")
    _git(clone, "config", "branch.topic.remote", ".")
    _git(clone, "config", "branch.topic.merge", "refs/heads/origin/main")

    _pull_in(qtbot, clone)

    assert _git(clone, "rev-parse", "topic") == _git(clone, "rev-parse", "refs/heads/origin/main")
    assert _git(clone, "rev-parse", "refs/remotes/origin/main") != pushed  # origin not fetched
