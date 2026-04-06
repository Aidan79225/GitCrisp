# git_gui/presentation/widgets/file_list_view.py
"""Shared QListView subclass with click-to-deselect support."""
from __future__ import annotations
from PySide6.QtCore import QModelIndex, Signal
from PySide6.QtWidgets import QListView


class FileListView(QListView):
    """QListView that emits ``deselected`` when the user clicks the already-selected row.

    Overrides ``mousePressEvent`` so that clicking a currently-selected row
    clears the selection immediately — without delegating to ``super()`` first —
    which prevents Qt from re-selecting the row and leaving a blue highlight.
    """

    deselected = Signal()

    def mousePressEvent(self, event) -> None:
        clicked = self.indexAt(event.pos())
        current = self.currentIndex()
        if (clicked.isValid() and clicked == current
                and self.selectionModel().isSelected(current)):
            # Handle deselect ourselves — don't pass to super() so Qt cannot
            # re-select the row and leave the blue background visible.
            self.selectionModel().clear()
            self.setCurrentIndex(QModelIndex())
            self.viewport().update()
            self.deselected.emit()
            return
        super().mousePressEvent(event)
