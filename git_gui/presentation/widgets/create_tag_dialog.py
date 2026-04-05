from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout,
)


class CreateTagDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Tag")
        self.setMinimumWidth(350)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Tag name:"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. v1.0.0")
        layout.addWidget(self._name_edit)

        layout.addWidget(QLabel("Message (optional — leave empty for lightweight tag):"))
        self._message_edit = QLineEdit()
        self._message_edit.setPlaceholderText("e.g. Release 1.0.0")
        layout.addWidget(self._message_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Create")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._name_edit.setFocus()

    def _on_accept(self) -> None:
        if self._name_edit.text().strip():
            self.accept()

    def tag_name(self) -> str:
        return self._name_edit.text().strip()

    def tag_message(self) -> str | None:
        text = self._message_edit.text().strip()
        return text if text else None
