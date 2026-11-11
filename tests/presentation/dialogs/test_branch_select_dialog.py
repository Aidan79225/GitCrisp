"""Tests for BranchSelectDialog."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from git_gui.presentation.dialogs.branch_select_dialog import BranchSelectDialog


def test_double_clicking_a_branch_picks_it(qtbot):
    dlg = BranchSelectDialog(["main", "feature"])
    qtbot.addWidget(dlg)

    dlg._list.setCurrentRow(1)
    dlg._list.itemDoubleClicked.emit(dlg._list.item(1))

    assert dlg.result() == QDialog.DialogCode.Accepted
    assert dlg.selected() == "feature"


def _cancel_the_dialog_that_is_up() -> None:
    dialog = QApplication.activeModalWidget()
    if dialog is not None:
        dialog.reject()


def test_a_closed_dialog_is_freed_once_its_owner_lets_go_of_it(qtbot):
    """Double-clicking an entry used to be connected through a lambda that
    captured the dialog, which kept every dialog the window had run under it,
    11 widgets each.

    The exec() is the real one: a stub skips what PySide does to a dialog it
    runs, and every dialog then looks as if it had been leaked.
    """
    window = QWidget()
    qtbot.addWidget(window)

    for opening in (1, 2):
        QTimer.singleShot(0, _cancel_the_dialog_that_is_up)
        result = BranchSelectDialog(["main", "feature"], parent=window).exec()

        assert result == QDialog.DialogCode.Rejected
        left = len(window.findChildren(BranchSelectDialog))
        assert left == 0, (
            f"{left} Checkout Branch dialog(s) still under the window after opening {opening}"
        )
