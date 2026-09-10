"""Auto-refresh has to be running before the user does anything.

The detector was built only inside the repo-switch handler, so a window opened
straight onto a repo — how the app normally starts — had none at all. Nothing
done outside GitCrisp registered until the user happened to switch repos and
back, which is not a thing anyone does, so the feature read as simply broken.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.presentation.main_window import MainWindow


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path) -> Path:
    path = tmp_path / "r"
    path.mkdir()
    _git(path, "init", "-q", ".")
    _git(path, "config", "user.name", "T")
    _git(path, "config", "user.email", "t@e.com")
    (path / "a.txt").write_text("x\n")
    _git(path, "add", "a.txt")
    _git(path, "commit", "-qm", "init")
    return path


def _window(qtbot, path: Path | None) -> MainWindow:
    from main import _open_session

    queries, commands = _open_session(str(path)) if path is not None else (None, None)
    win = MainWindow(
        queries,
        commands,
        JsonRepoStore(),
        JsonRemoteTagCache(),
        str(path) if path is not None else None,
        session_factory=_open_session,
    )
    qtbot.addWidget(win)
    return win


def test_a_window_opened_on_a_repo_is_already_watching_it(qtbot, repo):
    win = _window(qtbot, repo)

    assert win._change_detector is not None
    watched = set(win._change_detector._watcher.files())
    assert str(repo / ".git" / "HEAD") in watched


def test_a_window_with_no_repo_watches_nothing(qtbot):
    """The empty state has no path to watch, and constructing a detector on
    None would fail at startup rather than at the point of use."""
    win = _window(qtbot, None)

    assert win._change_detector is None


def test_a_commit_made_outside_the_app_reaches_the_window(qtbot, repo):
    """The behaviour the detector exists for, from a plain launch."""
    win = _window(qtbot, repo)
    reloads: list[None] = []
    win._change_detector._on_reload = lambda: reloads.append(None)

    (repo / "a.txt").write_text("changed\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-qm", "outside the app")

    qtbot.waitUntil(lambda: bool(reloads), timeout=5000)


def test_switching_repos_replaces_the_watch(qtbot, repo, tmp_path):
    """One detector at a time: a window still watching the repo it left would
    reload the new one every time the old one changed."""
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q", ".")
    _git(other, "config", "user.name", "T")
    _git(other, "config", "user.email", "t@e.com")
    (other / "b.txt").write_text("y\n")
    _git(other, "add", "b.txt")
    _git(other, "commit", "-qm", "init")

    win = _window(qtbot, repo)
    first = win._change_detector

    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        win._switch_repo(str(other))

    assert win._change_detector is not first
    watched = set(win._change_detector._watcher.files())
    assert str(other / ".git" / "HEAD") in watched
    assert str(repo / ".git" / "HEAD") not in watched
