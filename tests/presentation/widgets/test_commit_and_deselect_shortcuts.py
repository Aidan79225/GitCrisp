"""Tests for the working-tree keyboard shortcuts: Ctrl+Enter commits, Esc deselects."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QStringListModel, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication

from git_gui.presentation.widgets.file_list_view import FileListView
from git_gui.presentation.widgets.working_tree import WorkingTreeWidget


@pytest.fixture
def tree(qtbot):
    w = WorkingTreeWidget(MagicMock(), MagicMock())
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    w.activateWindow()
    w._msg_edit.setFocus()
    QApplication.processEvents()
    commits: list[bool] = []
    w._on_commit = lambda: commits.append(True)  # type: ignore[method-assign]
    return w, commits


@pytest.mark.parametrize("key", [Qt.Key_Return, Qt.Key_Enter])
def test_ctrl_enter_in_message_editor_commits(tree, qtbot, key):
    w, commits = tree
    qtbot.keyClick(w._msg_edit, key, Qt.ControlModifier)
    assert commits == [True]


def test_plain_enter_stays_a_newline(tree, qtbot):
    w, commits = tree
    qtbot.keyClick(w._msg_edit, Qt.Key_Return)
    assert commits == []
    assert w._msg_edit.toPlainText() == "\n"


def test_ctrl_enter_does_nothing_while_commit_is_disabled(tree, qtbot):
    w, commits = tree
    w._btn_commit.setEnabled(False)
    qtbot.keyClick(w._msg_edit, Qt.Key_Return, Qt.ControlModifier)
    assert commits == []


def test_commit_button_tooltip_names_the_shortcut(tree):
    # In the platform's own spelling: "Ctrl+Return" here, "⌘↵" on macOS.
    w, _ = tree
    native = QKeySequence("Ctrl+Return").toString(QKeySequence.NativeText)
    assert native in w._btn_commit.toolTip()


def _file_view(qtbot):
    view = FileListView()
    view.setModel(QStringListModel(["a.py", "b.py"]))
    qtbot.addWidget(view)
    return view


def test_esc_clears_a_selected_row(qtbot):
    view = _file_view(qtbot)
    view.setCurrentIndex(view.model().index(0))
    with qtbot.waitSignal(view.deselected, timeout=1000):
        qtbot.keyClick(view, Qt.Key_Escape)
    assert not view.selectionModel().hasSelection()
    assert not view.currentIndex().isValid()


def test_esc_with_nothing_selected_is_passed_on(qtbot):
    view = _file_view(qtbot)
    fired: list[bool] = []
    view.deselected.connect(lambda: fired.append(True))
    qtbot.keyClick(view, Qt.Key_Escape)
    assert fired == []
