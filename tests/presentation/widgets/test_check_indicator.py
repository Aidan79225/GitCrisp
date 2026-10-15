"""The check indicator of a checkable row is painted by the delegate, every row.

Qt's macOS style on macOS 27 draws item-view check boxes outside the view for
every row but the first (QTBUG-150017), so these tests read the rendered
pixels of rows past the first rather than trusting the style.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QListView

from git_gui.domain.entities import FileDelta, FileStatus, StagingState
from git_gui.presentation.dialogs.remote_branches_dialog import RemoteBranchesDialog
from git_gui.presentation.theme import ColorRole, get_theme_manager
from git_gui.presentation.widgets.check_indicator import (
    CheckIndicatorDelegate,
    indicator_box,
)
from git_gui.presentation.widgets.file_list_view import FileListView
from git_gui.presentation.widgets.working_tree import _FileDelegate
from git_gui.presentation.widgets.working_tree_model import WorkingTreeModel

_FILES = [
    FileStatus("a/staged.py", StagingState.STAGED, FileDelta.MODIFIED),
    FileStatus("b/partial.py", StagingState.UNSTAGED, FileDelta.MODIFIED),
    FileStatus("c/untracked.txt", StagingState.UNTRACKED, FileDelta.ADDED),
]


def _color(role: ColorRole) -> QColor:
    return get_theme_manager().current.colors.as_qcolor(role)


def _close(actual: QColor, expected: QColor, tolerance: int = 12) -> bool:
    return all(
        abs(a - e) <= tolerance
        for a, e in zip(actual.getRgb()[:3], expected.getRgb()[:3], strict=True)
    )


def _pixel(image, point: QPoint) -> QColor:
    ratio = image.devicePixelRatio()
    return image.pixelColor(round(point.x() * ratio), round(point.y() * ratio))


@pytest.fixture
def view(qtbot):
    v = FileListView()
    v.setEditTriggers(QListView.NoEditTriggers)
    v.setItemDelegate(_FileDelegate(v))
    model = WorkingTreeModel(MagicMock(), v)
    v.setModel(model)
    model.reload(_FILES, {"b/partial.py"})
    v.resize(400, 120)
    qtbot.addWidget(v)
    v.show()
    qtbot.waitExposed(v)
    QApplication.processEvents()
    return v


def _box_points(view, row: int) -> tuple[QPoint, QPoint]:
    """A point on the box's top border and one just inside it, clear of the glyph."""
    index = view.model().index(row)
    check = view._checkbox_rect(index)
    row_rect = view.visualRect(index)
    box = indicator_box(QRect(check.left(), row_rect.top(), check.width(), row_rect.height()))
    x = box.center().x()
    return QPoint(x, box.top() + 1), QPoint(x, box.top() + 4)


def test_every_row_gets_an_indicator(view):
    image = view.viewport().grab().toImage()
    accent = _color(ColorRole.ON_PRIMARY_CONTAINER)

    border, inside = _box_points(view, 0)  # checked
    assert _close(_pixel(image, border), accent)
    assert _close(_pixel(image, inside), accent)

    border, inside = _box_points(view, 1)  # partially checked
    assert _close(_pixel(image, border), accent)
    assert _close(_pixel(image, inside), accent)

    border, inside = _box_points(view, 2)  # unchecked
    assert _close(_pixel(image, border), _color(ColorRole.OUTLINE))
    assert _close(_pixel(image, inside), _color(ColorRole.SURFACE))


def test_remote_branches_table_paints_its_own_indicators(qtbot):
    queries = MagicMock()
    queries.get_branches.execute.return_value = []
    dialog = RemoteBranchesDialog(queries, MagicMock())
    qtbot.addWidget(dialog)
    assert isinstance(dialog._table.itemDelegate(), CheckIndicatorDelegate)
