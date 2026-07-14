from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)


class BranchSelectDialog(QDialog):
    """Pick one branch to check out when a commit carries several.

    Presented only when a double-clicked commit has more than one candidate
    branch. Follows the app's global theme — no inline colors. Double-clicking
    an entry (or Ok) confirms the selection.
    """

    def __init__(self, branches: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Checkout Branch")

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("This commit has several branches. Choose one to check out:"))

        self._list = QListWidget()
        for name in branches:
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, name)
            self._list.addItem(item)
        if branches:
            self._list.setCurrentRow(0)
        self._list.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self._list)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Checkout")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected(self) -> str | None:
        item = self._list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None
