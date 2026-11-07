"""A clone's signals are deleted by Qt on the GUI thread, whichever thread lets go of them.

The worker answers through a signals object. Parentless, it died with its last
Python reference, and nothing decides which thread drops that: the worker, still
unwinding when the window has already freed the dialog, or whichever thread the
garbage collector runs on once it reaches the dialog's wrapper, which a
reference cycle of the theme listener keeps alive after its C++ object is gone.
Qt documents deleting a QObject from a thread other than its own as unsafe. A
child of the dialog that deletes itself once its clone has ended is deleted by
Qt, on the GUI thread.

The signals go with the dialog, so a worker finishing after the dialog is gone
must not fail for it.
"""

from __future__ import annotations

import gc
import threading
from unittest.mock import patch

import pytest
import shiboken6
from PySide6.QtWidgets import QDialog

from git_gui.presentation.widgets import clone_dialog
from git_gui.presentation.widgets.clone_dialog import CloneDialog
from tests.presentation.thread_helpers import recording
from tests.presentation.window_helpers import blank_window

_URL = "https://example.com/user/repo.git"


@pytest.fixture
def destroyed_on(monkeypatch) -> list[str]:
    """The name of the thread that destroyed each clone's signals, as they are destroyed."""
    names: list[str] = []
    monkeypatch.setattr(clone_dialog, "_CloneSignals", recording(clone_dialog._CloneSignals, names))
    return names


def _collect_garbage_on_another_thread() -> None:
    collector = threading.Thread(target=gc.collect, name="a-busy-worker")
    collector.start()
    collector.join(10)
    assert not collector.is_alive()


def test_a_clones_signals_are_destroyed_on_the_gui_thread_when_another_thread_collects_garbage(
    qtbot, destroyed_on
):
    win = blank_window(qtbot)
    win._on_clone_completed = lambda _path: None

    def clone_to_the_end(dialog: CloneDialog) -> QDialog.DialogCode:
        dialog.show()
        dialog._url_edit.setText(_URL)
        with qtbot.waitSignal(dialog.accepted):
            dialog._on_clone()
        return QDialog.DialogCode.Accepted

    gc.collect()  # what is garbage by now is freed here, on the GUI thread
    gc.disable()  # from here on, garbage is collected only where the test says
    try:
        with (
            patch.object(clone_dialog, "clone_repo"),
            patch.object(CloneDialog, "exec", clone_to_the_end),
        ):
            win._on_clone_requested()
        qtbot.waitUntil(lambda: win.findChildren(CloneDialog) == [])
        _collect_garbage_on_another_thread()
    finally:
        gc.enable()

    assert destroyed_on == [threading.current_thread().name]


def test_a_clones_signals_are_deleted_on_the_gui_thread_once_it_has_ended(qtbot, destroyed_on):
    """A dialog that stays open for another try does not keep the signals of the one that failed."""
    dialog = CloneDialog()
    qtbot.addWidget(dialog)
    dialog._url_edit.setText(_URL)

    with patch.object(clone_dialog, "clone_repo", side_effect=RuntimeError("boom")):
        dialog._on_clone()
        qtbot.waitUntil(lambda: bool(destroyed_on))

    assert destroyed_on == [threading.current_thread().name]


def test_a_dialog_destroyed_mid_clone_takes_its_signals_along_and_the_worker_raises_nothing(
    monkeypatch, destroyed_on
):
    raised: list[BaseException | None] = []
    monkeypatch.setattr(threading, "excepthook", lambda args: raised.append(args.exc_value))
    in_clone, git_finishes = threading.Event(), threading.Event()
    workers: list[threading.Thread] = []

    def clone_until_git_finishes(url, dest, on_progress=None, cancelled=None):
        workers.append(threading.current_thread())
        in_clone.set()
        git_finishes.wait(5)

    dialog = CloneDialog()
    dialog._url_edit.setText(_URL)
    try:
        with patch.object(clone_dialog, "clone_repo", clone_until_git_finishes):
            dialog._on_clone()
            assert in_clone.wait(5), "the clone never started"
            shiboken6.delete(dialog)  # closed with the clone still running
        assert destroyed_on == [threading.current_thread().name]
    finally:
        git_finishes.set()
        if shiboken6.isValid(dialog):
            shiboken6.delete(dialog)
    workers[0].join(5)
    assert not workers[0].is_alive()

    assert raised == []
