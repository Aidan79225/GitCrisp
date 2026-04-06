# git_gui/presentation/widgets/file_list_view.py
"""Shared QListView subclass with click-to-deselect and checkbox-without-select."""
from __future__ import annotations
from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtWidgets import QListView, QStyle, QStyleOptionViewItem


class FileListView(QListView):
    """QListView with two custom click behaviors:

    1. Clicking the checkbox indicator toggles the check state WITHOUT changing
       the row selection (so the blue highlight on another row is preserved).
    2. Clicking an already-selected row deselects it and emits ``deselected``,
       without delegating to ``super()`` so Qt cannot re-select.
    """

    deselected = Signal()

    def _checkbox_rect(self, index):
        """Return the QRect of the check indicator for *index*, or None."""
        if not index.isValid():
            return None
        opt = QStyleOptionViewItem()
        self.initViewItemOption(opt)
        opt.rect = self.visualRect(index)
        opt.features |= QStyleOptionViewItem.HasCheckIndicator
        return self.style().subElementRect(
            QStyle.SE_ItemViewItemCheckIndicator, opt, self
        )

    def mousePressEvent(self, event) -> None:
        clicked = self.indexAt(event.pos())

        # Case 1: click on the checkbox indicator → toggle without selection change
        if clicked.isValid() and (self.model().flags(clicked) & Qt.ItemIsUserCheckable):
            check_rect = self._checkbox_rect(clicked)
            if check_rect is not None and check_rect.contains(event.pos()):
                current = clicked.data(Qt.CheckStateRole)
                # current may be Qt.CheckState enum or int — normalize
                checked_val = int(Qt.CheckState.Checked.value) if hasattr(Qt.CheckState.Checked, "value") else int(Qt.Checked)
                is_checked = int(current) == checked_val
                new_state = Qt.CheckState.Unchecked if is_checked else Qt.CheckState.Checked
                self.model().setData(clicked, new_state, Qt.CheckStateRole)
                return  # do NOT call super → selection unchanged

        # Case 2: click on the already-selected row → deselect
        current = self.currentIndex()
        if (clicked.isValid() and clicked == current
                and self.selectionModel().isSelected(current)):
            self.selectionModel().clear()
            self.setCurrentIndex(QModelIndex())
            self.viewport().update()
            self.deselected.emit()
            return

        super().mousePressEvent(event)
