"""Application preferences dialog.

Today: a single ``Check for updates on startup`` checkbox. Designed to
grow — future preferences (Sentry opt-out, language, etc.) plug into
the same form layout.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QVBoxLayout,
    QWidget,
)

from git_gui.presentation.app_settings import get_check_updates, set_check_updates


class PreferencesDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setModal(True)

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self._check_updates_box = QCheckBox("Check for updates on startup")
        self._check_updates_box.setChecked(get_check_updates())
        form.addRow(self._check_updates_box)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        set_check_updates(self._check_updates_box.isChecked())
        super().accept()
