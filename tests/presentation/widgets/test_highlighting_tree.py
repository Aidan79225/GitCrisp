"""The shared row highlighting of the sidebar and repository list trees."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QStandardItem, QStandardItemModel
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


def test_the_tree_turns_on_the_mouse_tracking_its_hover_needs(qtbot):
    """Qt delivers a move with no button held only to a widget that tracks
    the mouse, so without it no row is ever hovered. (The hover tests below
    send their moves directly, which skips that check.)"""
    tree = HighlightingTreeView(_FLAG_ROLE)
    qtbot.addWidget(tree)

    assert tree.viewport().hasMouseTracking()


def test_the_flagged_row_is_filled_with_primary(qtbot):
    tree = _shown_tree(qtbot)

    assert tree._row_fill(tree.model().index(0, 0)) == _role_color(ColorRole.PRIMARY)


def test_the_hovered_row_is_filled_with_the_hover_overlay(qtbot):
    """The commit list hovers with HOVER_OVERLAY, and so the Appearance
    dialog's hover_overlay swatch must reach these trees too."""
    tree = _shown_tree(qtbot)

    _hover(tree, 1)

    assert tree._row_fill(tree.model().index(1, 0)) == _role_color(ColorRole.HOVER_OVERLAY)


def _laid_over(overlay: QColor, base: QColor, image_format: QImage.Format) -> QColor:
    pixel = QImage(1, 1, image_format)
    pixel.fill(base)
    painter = QPainter(pixel)
    painter.fillRect(0, 0, 1, 1, overlay)
    painter.end()
    return pixel.pixelColor(0, 0)


def test_the_hover_overlay_is_laid_once_over_the_whole_row(qtbot):
    """The overlay is translucent: filling the branch column and then the
    row would lay it there twice, a stronger block beside the name."""
    tree = _shown_tree(qtbot)
    _hover(tree, 1)

    image = tree.viewport().grab().toImage()

    def pixel(x: int, row: int) -> QColor:
        y = tree.visualRect(tree.model().index(row, 0)).center().y()
        ratio = image.devicePixelRatio()
        return image.pixelColor(round(x * ratio), round(y * ratio))

    overlay = _role_color(ColorRole.HOVER_OVERLAY)
    for x in (2, tree.viewport().width() - 3):  # the branch column, then past the name
        assert pixel(x, 1) == _laid_over(overlay, pixel(x, 2), image.format())


def test_a_row_neither_flagged_nor_hovered_is_left_unfilled(qtbot):
    tree = _shown_tree(qtbot)

    _hover(tree, 1)

    assert tree._row_fill(tree.model().index(2, 0)) is None
