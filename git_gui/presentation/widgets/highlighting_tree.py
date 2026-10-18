from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QPoint
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QStyleOptionViewItem, QTreeView

from git_gui.presentation.theme import ColorRole, get_theme_manager


class HighlightingTreeView(QTreeView):
    """A tree that fills one flagged row and the hovered row edge to edge.

    A row whose *highlight_role* data is truthy (the HEAD branch, the open
    repo) is filled with PRIMARY; the row under the mouse with
    SURFACE_CONTAINER_HIGH. The branch (indent) column is filled too, which
    the delegate alone cannot reach.
    """

    def __init__(self, highlight_role: int, parent=None) -> None:
        super().__init__(parent)
        self._highlight_role = highlight_role
        self._hover_idx = QPersistentModelIndex()

    def mouseMoveEvent(self, event) -> None:
        self._track_hover(event.position().toPoint())
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hover_idx.isValid():
            self._hover_idx = QPersistentModelIndex()
            self.viewport().update()
        super().leaveEvent(event)

    def _track_hover(self, pos: QPoint) -> None:
        idx = self.indexAt(pos)
        new_idx = QPersistentModelIndex(idx) if idx.isValid() else QPersistentModelIndex()
        if new_idx != self._hover_idx:
            self._hover_idx = new_idx
            self.viewport().update()

    def _row_fill(self, index: QModelIndex) -> QColor | None:
        colors = get_theme_manager().current.colors
        if index.data(self._highlight_role):
            return colors.as_qcolor(ColorRole.PRIMARY)
        if self._hover_idx.isValid() and index == self._hover_idx:
            return colors.as_qcolor(ColorRole.SURFACE_CONTAINER_HIGH)
        return None

    def drawBranches(self, painter, rect, index) -> None:
        fill = self._row_fill(index)
        if fill is not None:
            painter.fillRect(rect, fill)
        super().drawBranches(painter, rect, index)

    def drawRow(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        fill = self._row_fill(index)
        if fill is not None:
            painter.save()
            painter.fillRect(option.rect, fill)
            painter.restore()
        super().drawRow(painter, option, index)
