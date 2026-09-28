from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from git_gui.presentation.app_settings import get_push_new_tags, set_push_new_tags


class CreateTagDialog(QDialog):
    def __init__(self, parent=None, can_push: bool = True) -> None:
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

        self._can_push = can_push
        self._push_box = QCheckBox("Push to origin")
        if can_push:
            self._push_box.setChecked(get_push_new_tags())
        else:
            self._push_box.setEnabled(False)
            self._push_box.setToolTip("This repository has no remote named 'origin'.")
        layout.addWidget(self._push_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Create")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._name_edit.setFocus()

    def _on_accept(self) -> None:
        if self._name_edit.text().strip():
            # Remembered only when the choice was the user's to make: a repo
            # without origin must not reset the preference for every other.
            if self._can_push:
                set_push_new_tags(self._push_box.isChecked())
            self.accept()

    def tag_name(self) -> str:
        return self._name_edit.text().strip()

    def tag_message(self) -> str | None:
        text = self._message_edit.text().strip()
        return text if text else None

    def push_requested(self) -> bool:
        return self._can_push and self._push_box.isChecked()
