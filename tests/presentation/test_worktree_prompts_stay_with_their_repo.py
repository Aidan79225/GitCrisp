"""A worktree removal or lock the user agreed to runs in the repo they were asked about.

Remove, Force remove and Lock each ask first, and the prompt runs a nested
event loop: a repo switch already on its way lands while it is up. The flows
read the window's bus only once the prompt had closed, so the first repo's
worktree was handed to the other repo's git, which refused it with an error
that made no sense to the user ("... is not a working tree").
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QInputDialog, QMessageBox

from git_gui.infrastructure.worktree_cli import WorktreeDirtyError, WorktreeLockedError
from git_gui.presentation.main_window import MainWindow
from tests.presentation.window_helpers import empty_repo_store

_WORKTREE = "/repo-feature"


def _session(_path: str = "/repo") -> tuple[MagicMock, MagicMock]:
    queries = MagicMock()
    queries.list_worktrees.execute.return_value = []
    return queries, MagicMock()


@pytest.fixture
def win(qtbot) -> MainWindow:
    w = MainWindow(
        queries=None, commands=None, repo_store=empty_repo_store(), session_factory=_session
    )
    qtbot.addWidget(w)
    w._queries, w._commands = _session()
    w._repo_path = "/repo"
    return w


def _open_another_repo(qtbot, win: MainWindow) -> None:
    """Let a pending repo switch land now, as a prompt's nested loop would."""
    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        win._switch_repo("/other")


def _force_remove_once_another_repo_opens(qtbot, win: MainWindow):
    def _exec(box: QMessageBox) -> int:
        _open_another_repo(qtbot, win)
        next(b for b in box.buttons() if box.buttonRole(b) == QMessageBox.DestructiveRole).click()
        return 0

    return _exec


def _skipped(win: MainWindow, op_name: str) -> bool:
    return f"{op_name} — skipped: another repo opened" in win._log_panel._body.toPlainText()


def _assert_never_ran_in(command: str, *buses: MagicMock) -> None:
    for bus in buses:
        getattr(bus, command).execute.assert_not_called()


def test_a_removal_confirmed_as_another_repo_opens_removes_nothing(qtbot, win, monkeypatch):
    asked_in = win._commands

    def _yes_once_another_repo_opens(*_args, **_kwargs):
        _open_another_repo(qtbot, win)
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "question", _yes_once_another_repo_opens)

    win._begin_remove_worktree(_WORKTREE)

    assert _skipped(win, f"Remove worktree {_WORKTREE}")
    qtbot.wait(200)  # a removal that did start runs on a worker thread
    _assert_never_ran_in("remove_worktree", asked_in, win._commands)


def test_a_removal_confirmed_in_the_same_repo_runs(qtbot, win, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.Yes)

    win._begin_remove_worktree(_WORKTREE)

    qtbot.waitUntil(lambda: win._commands.remove_worktree.execute.called, timeout=2000)


def test_a_lock_given_its_reason_as_another_repo_opens_locks_nothing(qtbot, win, monkeypatch):
    asked_in = win._commands

    def _reason_once_another_repo_opens(*_args, **_kwargs):
        _open_another_repo(qtbot, win)
        return "on a USB stick", True

    monkeypatch.setattr(QInputDialog, "getText", _reason_once_another_repo_opens)

    win._run_lock_worktree(_WORKTREE)

    assert _skipped(win, f"Lock worktree {_WORKTREE}")
    qtbot.wait(200)
    _assert_never_ran_in("lock_worktree", asked_in, win._commands)


@pytest.mark.parametrize("refusal", [WorktreeDirtyError, WorktreeLockedError])
def test_a_force_remove_agreed_as_another_repo_opens_removes_nothing(
    qtbot, win, monkeypatch, refusal
):
    asked_in = win._commands
    asked_in.remove_worktree.execute.side_effect = refusal("refused")
    monkeypatch.setattr(QMessageBox, "exec", _force_remove_once_another_repo_opens(qtbot, win))

    win._run_remove_worktree(_WORKTREE, force=False)

    qtbot.waitUntil(lambda: _skipped(win, f"Remove worktree {_WORKTREE}"), timeout=5000)
    qtbot.wait(200)
    assert asked_in.remove_worktree.execute.call_count == 1
    _assert_never_ran_in("remove_worktree", win._commands)


def test_a_force_remove_offered_after_another_repo_opened_removes_nothing(qtbot, win, monkeypatch):
    """The repo changed while the first attempt ran, before the prompt went up."""
    asked_in = win._commands
    attempted = threading.Event()

    def _refuse_once_released(*_args, **_kwargs):
        attempted.wait(5)
        raise WorktreeDirtyError("has changes")

    asked_in.remove_worktree.execute.side_effect = _refuse_once_released

    def _force_remove(box: QMessageBox) -> int:
        next(b for b in box.buttons() if box.buttonRole(b) == QMessageBox.DestructiveRole).click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", _force_remove)

    win._run_remove_worktree(_WORKTREE, force=False)
    _open_another_repo(qtbot, win)
    attempted.set()

    qtbot.waitUntil(lambda: _skipped(win, f"Remove worktree {_WORKTREE}"), timeout=5000)
    qtbot.wait(200)
    _assert_never_ran_in("remove_worktree", win._commands)
