"""Signal-contract tests for WorktreesDialog."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from git_gui.domain.entities import Worktree
from git_gui.presentation.dialogs.worktrees_dialog import WorktreesDialog


def _wt(branch="feat", path="/tmp/wt", locked=False, reason=None, main=False):
    return Worktree(
        path=path,
        branch=branch,
        head_sha="abc",
        is_locked=locked,
        lock_reason=reason,
        is_bare=False,
        is_main=main,
    )


def _open(qtbot, worktrees):
    dlg = WorktreesDialog(worktrees=worktrees)
    qtbot.addWidget(dlg)
    return dlg


def test_rows_render_branch_and_path(qtbot):
    dlg = _open(qtbot, [_wt("main", "/tmp/main", main=True), _wt("feat", "/tmp/wt-feat")])
    assert dlg.row_count() == 2
    assert dlg.row_branch(0) == "main"
    assert dlg.row_path(1) == "/tmp/wt-feat"


def test_locked_column_shows_reason(qtbot):
    dlg = _open(qtbot, [_wt("feat", locked=True, reason="busy")])
    assert dlg.row_locked_text(0) == "busy"


def test_locked_column_says_locked_when_no_reason_was_given(qtbot):
    dlg = _open(qtbot, [_wt("feat", locked=True, reason=None)])
    assert dlg.row_locked_text(0) == "Locked"


def test_open_button_emits_open_requested(qtbot):
    dlg = _open(qtbot, [_wt("feat", "/tmp/wt-feat")])
    received: list[str] = []
    dlg.open_requested.connect(received.append)
    dlg.select_row(0)
    dlg.click_open()
    assert received == ["/tmp/wt-feat"]


def test_remove_button_emits_remove_requested(qtbot):
    dlg = _open(qtbot, [_wt("feat", "/tmp/wt-feat")])
    received: list[str] = []
    dlg.remove_requested.connect(received.append)
    dlg.select_row(0)
    dlg.click_remove()
    assert received == ["/tmp/wt-feat"]


def test_lock_button_emits_lock_requested_for_unlocked_row(qtbot):
    dlg = _open(qtbot, [_wt("feat", "/tmp/wt-feat", locked=False)])
    received: list[str] = []
    dlg.lock_requested.connect(received.append)
    dlg.select_row(0)
    dlg.click_lock()
    assert received == ["/tmp/wt-feat"]


def test_unlock_button_emits_unlock_requested_for_locked_row(qtbot):
    dlg = _open(qtbot, [_wt("feat", "/tmp/wt-feat", locked=True)])
    received: list[str] = []
    dlg.unlock_requested.connect(received.append)
    dlg.select_row(0)
    dlg.click_unlock()
    assert received == ["/tmp/wt-feat"]


def test_add_button_emits_add_requested(qtbot):
    dlg = _open(qtbot, [])
    received: list = []
    dlg.add_requested.connect(lambda: received.append(True))
    dlg.click_add()
    assert received == [True]


def test_clicking_the_add_button_emits_add_requested(qtbot):
    """The button itself: click_add() emits the signal without going through it."""
    dlg = _open(qtbot, [])
    received: list = []
    dlg.add_requested.connect(lambda: received.append(True))
    dlg._add_btn.click()
    assert received == [True]


def test_opening_a_worktree_closes_the_dialog(qtbot):
    dlg = _open(qtbot, [_wt("feat", "/tmp/wt-feat")])
    dlg.show()
    dlg.select_row(0)
    dlg.click_open()
    assert not dlg.isVisible()


def test_set_worktrees_shows_a_lock_taken_after_opening(qtbot):
    dlg = _open(qtbot, [_wt("feat", "/tmp/wt-feat")])
    dlg.set_worktrees([_wt("feat", "/tmp/wt-feat", locked=True, reason="overnight")])
    assert dlg.row_locked_text(0) == "overnight"


def test_set_worktrees_drops_a_removed_worktree(qtbot):
    dlg = _open(qtbot, [_wt("main", "/tmp/main", main=True), _wt("feat", "/tmp/wt-feat")])
    dlg.set_worktrees([_wt("main", "/tmp/main", main=True)])
    assert [dlg.row_path(r) for r in range(dlg.row_count())] == ["/tmp/main"]


def _cancel_the_dialog_that_is_up() -> None:
    dialog = QApplication.activeModalWidget()
    if dialog is not None:
        dialog.reject()


def test_a_closed_dialog_is_freed_once_its_owner_lets_go_of_it(qtbot):
    """The Add button used to be connected through a lambda that captured the
    dialog, which kept every dialog the window had run under it, 26 widgets each.

    The exec() is the real one: a stub skips what PySide does to a dialog it
    runs, and every dialog then looks as if it had been leaked.
    """
    window = QWidget()
    qtbot.addWidget(window)

    for opening in (1, 2):
        QTimer.singleShot(0, _cancel_the_dialog_that_is_up)
        result = WorktreesDialog(worktrees=[_wt()], parent=window).exec()

        assert result == QDialog.DialogCode.Rejected
        left = len(window.findChildren(WorktreesDialog))
        assert left == 0, (
            f"{left} Worktrees dialog(s) still under the window after opening {opening}"
        )
