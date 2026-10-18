"""The shared row highlighting of the sidebar and repository list trees."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QApplication

from git_gui.presentation.theme import ColorRole, get_theme_manager
from git_gui.presentation.widgets.highlighting_tree import HighlightingTreeView

_FLAG_ROLE = Qt.UserRole + 2


def _shown_tree(qtbot) -> HighlightingTreeView:
    model = QStandardItemModel()
    for name, flagged in (("main", True), ("feature", False), ("fix", False)):
        item = QStandardItem(name)
        item.setData(flagged, _FLAG_ROLE)
        model.appendRow(item)
    tree = HighlightingTreeView(_FLAG_ROLE)
    tree.setModel(model)
    tree.setMouseTracking(True)
    qtbot.addWidget(tree)
    tree.resize(200, 200)
    tree.show()
    qtbot.waitExposed(tree)
    return tree


def _hover(tree: HighlightingTreeView, row: int) -> None:
    pos = tree.visualRect(tree.model().index(row, 0)).center()
    move = QMouseEvent(
        QEvent.MouseMove,
        QPointF(pos),
        QPointF(tree.viewport().mapToGlobal(pos)),
        Qt.NoButton,
        Qt.NoButton,
        Qt.NoModifier,
    )
    QApplication.sendEvent(tree.viewport(), move)


def _role_color(role: ColorRole):
    return get_theme_manager().current.colors.as_qcolor(role)


def test_the_flagged_row_is_filled_with_primary(qtbot):
    tree = _shown_tree(qtbot)

    assert tree._row_fill(tree.model().index(0, 0)) == _role_color(ColorRole.PRIMARY)


def test_the_hovered_row_is_filled_with_the_hover_surface(qtbot):
    tree = _shown_tree(qtbot)

    _hover(tree, 1)

    assert tree._row_fill(tree.model().index(1, 0)) == _role_color(ColorRole.SURFACE_CONTAINER_HIGH)


def test_a_row_neither_flagged_nor_hovered_is_left_unfilled(qtbot):
    tree = _shown_tree(qtbot)

    _hover(tree, 1)

    assert tree._row_fill(tree.model().index(2, 0)) is None
