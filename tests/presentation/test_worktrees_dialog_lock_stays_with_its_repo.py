"""A lock asked for in the Worktrees dialog runs in the repo the dialog listed, or not at all.

The dialog asked for the lock's reason itself and handed the window the path
and the reason together, and the window locked it in whichever repo was open
by then. The reason prompt runs a nested event loop, so a switch already on
its way lands while it is up: the other repo's git, which does not know the
worktree, refused it with "No worktree at ...", and nothing was locked.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QInputDialog

from git_gui.domain.entities import Worktree
from git_gui.presentation.dialogs.worktrees_dialog import WorktreesDialog
from git_gui.presentation.main_window import MainWindow
from tests.presentation.window_helpers import empty_repo_store

_MAIN = "/repo"
_LINKED = "/repo-feature"


def _worktree(path: str, *, is_main: bool) -> Worktree:
    return Worktree(
        path=path,
        branch="master" if is_main else "feature",
        head_sha="a" * 40,
        is_locked=False,
        lock_reason=None,
        is_bare=False,
        is_main=is_main,
    )


def _session(_path: str = "/other") -> tuple[MagicMock, MagicMock]:
    queries = MagicMock()
    queries.list_worktrees.execute.return_value = []
    return queries, MagicMock()


@pytest.fixture
def win(qtbot) -> MainWindow:
    """The window on a repo with one linked worktree."""
    w = MainWindow(
        queries=None, commands=None, repo_store=empty_repo_store(), session_factory=_session
    )
    qtbot.addWidget(w)
    w._queries, w._commands = _session()
    w._queries.list_worktrees.execute.return_value = [
        _worktree(_MAIN, is_main=True),
        _worktree(_LINKED, is_main=False),
    ]
    w._repo_path = _MAIN
    return w


def _lock_the_linked_worktree_from_the_dialog(win: MainWindow, monkeypatch) -> None:
    def _exec(dialog: WorktreesDialog) -> int:
        dialog.select_row(1)
        dialog.click_lock()
        return 0

    monkeypatch.setattr(WorktreesDialog, "exec", _exec)
    win._open_worktrees_dialog()


def _log_text(win: MainWindow) -> str:
    return win._log_panel._body.toPlainText()


def test_a_lock_given_its_reason_as_another_repo_opens_locks_nothing(qtbot, win, monkeypatch):
    asked_in = win._commands

    def _reason_once_another_repo_opens(*_args, **_kwargs):
        with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
            win._switch_repo("/other")
        return "on a USB stick", True

    monkeypatch.setattr(QInputDialog, "getText", _reason_once_another_repo_opens)

    _lock_the_linked_worktree_from_the_dialog(win, monkeypatch)

    qtbot.wait(200)  # a lock that did start runs on a worker thread
    asked_in.lock_worktree.execute.assert_not_called()
    win._commands.lock_worktree.execute.assert_not_called()
    assert f"Lock worktree {_LINKED} — skipped: another repo opened" in _log_text(win)


def test_a_lock_given_its_reason_in_the_same_repo_runs_with_it(qtbot, win, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", lambda *_a, **_k: ("on a USB stick", True))

    _lock_the_linked_worktree_from_the_dialog(win, monkeypatch)

    lock = win._commands.lock_worktree.execute
    qtbot.waitUntil(lambda: lock.called, timeout=2000)
    lock.assert_called_once_with(_LINKED, reason="on a USB stick")


def test_a_lock_whose_reason_is_cancelled_locks_nothing(qtbot, win, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", lambda *_a, **_k: ("", False))

    _lock_the_linked_worktree_from_the_dialog(win, monkeypatch)

    qtbot.wait(200)
    win._commands.lock_worktree.execute.assert_not_called()
