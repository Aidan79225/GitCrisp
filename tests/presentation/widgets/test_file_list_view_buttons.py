"""Only the left button toggles a checkbox or deselects a row.

The right button opens the row's context menu, and the press that precedes
the menu must not stage a file or throw the diff back to the all-files view.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from git_gui.domain.entities import FileDelta, FileStatus, StagingState
from git_gui.presentation.widgets.check_indicator import CheckIndicatorDelegate
from git_gui.presentation.widgets.file_list_view import FileListView
from git_gui.presentation.widgets.working_tree_model import WorkingTreeModel


@pytest.fixture
def view(qtbot):
    commands = MagicMock()
    model = WorkingTreeModel(commands)
    model.reload(
        [
            FileStatus(path="a.txt", status=StagingState.UNSTAGED, delta=FileDelta.MODIFIED),
            FileStatus(path="b.txt", status=StagingState.UNSTAGED, delta=FileDelta.MODIFIED),
        ]
    )
    v = FileListView()
    v.setItemDelegate(CheckIndicatorDelegate(v))
    v.setModel(model)
    v.resize(300, 200)
    qtbot.addWidget(v)
    v.show()
    qtbot.waitExposed(v)
    return v, commands


def _check_point(v: FileListView, row: int):
    return v._checkbox_rect(v.model().index(row)).center()


def _row_text_point(v: FileListView, row: int):
    rect = v.visualRect(v.model().index(row))
    return rect.center()


def test_right_click_on_a_checkbox_does_not_stage(view):
    v, commands = view
    QTest.mouseClick(v.viewport(), Qt.RightButton, Qt.NoModifier, _check_point(v, 1))
    commands.stage_files.execute.assert_not_called()
    commands.unstage_files.execute.assert_not_called()


def test_left_click_on_a_checkbox_still_stages(view):
    v, commands = view
    QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, _check_point(v, 1))
    commands.stage_files.execute.assert_called_once_with(["b.txt"])


def test_right_click_on_the_selected_row_keeps_it_selected(view):
    v, _ = view
    v.setCurrentIndex(v.model().index(0))
    fired: list[bool] = []
    v.deselected.connect(lambda: fired.append(True))

    QTest.mouseClick(v.viewport(), Qt.RightButton, Qt.NoModifier, _row_text_point(v, 0))

    assert fired == []
    assert v.currentIndex().row() == 0
    assert v.selectionModel().isSelected(v.currentIndex())


def test_left_click_on_the_selected_row_still_deselects(view):
    v, _ = view
    v.setCurrentIndex(v.model().index(0))
    fired: list[bool] = []
    v.deselected.connect(lambda: fired.append(True))

    QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, _row_text_point(v, 0))

    assert fired == [True]
