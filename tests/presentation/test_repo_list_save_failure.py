"""Failing to write repos.json must not leave the window half switched.

The store was saved in the middle of the switch handler, and an OSError from
the write (a file briefly locked by antivirus or a sync client, a full disk)
escaped the slot. Qt only logged it, so the window stayed half on each repo:
the panes showed the new one while the title, the Git menu and the change
detector still belonged to the old one — and Git → Branches… acted on it.
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


def _repo(path: Path) -> str:
    path.mkdir()
    _git(path, "init", "-q", "-b", "master", ".")
    _git(path, "config", "user.name", "T")
    _git(path, "config", "user.email", "t@e.com")
    (path / "a.txt").write_text("x\n")
    _git(path, "add", "a.txt")
    _git(path, "commit", "-qm", "init")
    return str(path)


class _LockedStore(JsonRepoStore):
    def save(self) -> None:
        raise PermissionError("repos.json is locked by another process")


@pytest.fixture
def repos(tmp_path) -> tuple[str, str]:
    return _repo(tmp_path / "a"), _repo(tmp_path / "b")


@pytest.fixture
def window(qtbot, tmp_path, repos):
    from main import _open_session

    a, b = repos
    store = _LockedStore(tmp_path / "repos.json")
    JsonRepoStore.add_open(store, b)
    JsonRepoStore.add_open(store, a)
    queries, commands = _open_session(a)
    w = MainWindow(queries, commands, store, JsonRemoteTagCache(), a, session_factory=_open_session)
    qtbot.addWidget(w)
    return w


def _log_text(window) -> str:
    return window._log_panel._body.toPlainText()


def test_a_switch_finishes_when_the_repo_list_cannot_be_saved(qtbot, window, repos):
    _a, b = repos

    with qtbot.waitSignal(window._repo_ready_signals.ready, timeout=5000):
        window._switch_repo(b)

    assert window.windowTitle() == f"GitCrisp — {b}"
    assert str(Path(b) / ".git" / "HEAD") in window._change_detector._watcher.files()
    assert "Could not save the repo list" in _log_text(window)


def test_a_close_still_moves_on_when_the_repo_list_cannot_be_saved(qtbot, window, repos):
    _a, b = repos

    with qtbot.waitSignal(window._repo_ready_signals.ready, timeout=5000):
        window._close_current_repo()

    assert window._repo_path == b
