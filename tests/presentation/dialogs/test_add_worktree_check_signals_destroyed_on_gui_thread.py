"""A location check's signals are deleted by Qt on the GUI thread, never by its worker.

The Add Worktree dialog checks the location in its field on every change, on a worker
that answers through a signals object. One object, made with the dialog and shared by
every check, had no parent and so died with its last Python reference. While a check is
still reading a slow or dead share the worker's closure holds it beside the dialog, and
the dialog's opener frees the dialog as soon as the user has cancelled it, so the
worker, unwinding, was the last to let go of it.

Each check now answers through signals of its own, which belong to the application
(worker_signals) and go when the check's worker has returned (delete_when_done, which
test_background.py pins, a raising worker included). A dialog cancelled under a check
leaves them alive with nobody listening.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget

from git_gui.presentation.dialogs import add_worktree_dialog
from git_gui.presentation.dialogs.add_worktree_dialog import AddWorktreeDialog
from tests.presentation.thread_helpers import HeldFirstCall, deliver_queued_answers, recording
from tests.presentation.widgets.hunk_diff_helpers import workers_joined_on_exit


@pytest.fixture
def held_check(monkeypatch) -> HeldFirstCall:
    """A `_disk_problem` that parks the worker of the dialog's own first check until let go.

    Every later check finds the location fine at once.
    """
    held = HeldFirstCall(lambda: None)
    monkeypatch.setattr(add_worktree_dialog, "_disk_problem", held)
    return held


@pytest.fixture
def destroyed_on(monkeypatch) -> list[str]:
    """The name of the thread that destroyed each check's signals, as they are destroyed."""
    names: list[str] = []
    monkeypatch.setattr(
        add_worktree_dialog,
        "_LocationCheckSignals",
        recording(add_worktree_dialog._LocationCheckSignals, names),
    )
    return names


@pytest.fixture
def window(qtbot) -> QWidget:
    """Stands in for the main window, which the dialog is parented to, as in the app."""
    window = QWidget()
    qtbot.addWidget(window)
    return window


def _dialog(window: QWidget, folder: Path) -> AddWorktreeDialog:
    """A dialog whose own check, of its default location, is the one `held_check` parks."""
    return AddWorktreeDialog(repo_path=str(folder / "repo"), branches=["master"], parent=window)


def test_each_checks_signals_are_destroyed_on_the_gui_thread_once_its_worker_has_returned(
    qtbot, qapp, tmp_path, window, held_check, destroyed_on, worker_errors
):
    gui_thread = threading.current_thread().name
    with workers_joined_on_exit():
        dialog = _dialog(window, tmp_path)
        try:
            held_worker = held_check.gate.held_worker()  # the dialog's own check, still out
            dialog.set_location(str(tmp_path / "elsewhere"))  # a newer check, answered at once
            qtbot.waitUntil(dialog.add_button_enabled, timeout=5000)
        finally:
            held_check.gate.open()
        held_worker.join(5)
        assert not held_worker.is_alive()
    deliver_queued_answers()

    assert [name for name in destroyed_on if name != gui_thread] == []
    assert len(destroyed_on) == 2  # one per check: the older one's did not outlive its worker
    assert qapp.findChildren(add_worktree_dialog._LocationCheckSignals) == []  # none left over
    assert worker_errors == []  # the held worker's emit reached live signals


def _destroyed_while_checking(window: QWidget, folder: Path, held_check: HeldFirstCall):
    """The dialog's C++ object is deleted, and its wrapper goes as this returns."""
    dialog = _dialog(window, folder)
    worker = held_check.gate.held_worker()
    shiboken6.delete(dialog)
    return worker


def _reject_the_dialog_once_a_check_is_out(held_check: HeldFirstCall) -> None:
    try:
        held_check.gate.held_worker()  # inside its query, so the dialog goes with a check out
    finally:  # rejected even if no worker got in, or exec() would wait for ever
        dialog = QApplication.activeModalWidget()
        if dialog is not None:
            dialog.reject()


def _cancelled_while_checking(window: QWidget, folder: Path, held_check: HeldFirstCall):
    """What the window's opener does: run the dialog modally, then let go of it.

    The exec() is the real one: a stub skips what PySide does to a dialog it runs.
    """
    QTimer.singleShot(0, lambda: _reject_the_dialog_once_a_check_is_out(held_check))
    _dialog(window, folder).exec()
    return held_check.gate.held_worker()


# Every way the dialog goes while a check is out.
CLOSINGS = [
    pytest.param(_destroyed_while_checking, id="destroyed"),
    pytest.param(_cancelled_while_checking, id="cancelled"),
]


@pytest.mark.parametrize("close_dialog", CLOSINGS)
def test_a_dialogs_check_signals_outlive_it_until_the_worker_has_returned(
    tmp_path, window, held_check, destroyed_on, worker_errors, close_dialog
):
    gui_thread = threading.current_thread().name
    with workers_joined_on_exit():
        try:
            worker = close_dialog(window, tmp_path, held_check)
            assert window.findChildren(AddWorktreeDialog) == []
            deliver_queued_answers()
            # Deleted with the dialog, they would be gone under a worker about to emit.
            assert destroyed_on == []
        finally:
            held_check.gate.open()
        worker.join(5)
        assert not worker.is_alive()
    deliver_queued_answers()

    assert destroyed_on == [gui_thread]
    assert worker_errors == []
