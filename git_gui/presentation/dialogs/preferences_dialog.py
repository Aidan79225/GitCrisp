"""Application preferences dialog.

Update checks and crash reporting. Designed to grow — future preferences
(language, etc.) plug into the same form layout.
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

from git_gui.observability import set_crash_reporting_enabled
from git_gui.presentation.app_settings import (
    get_check_updates,
    get_send_crash_reports,
    set_check_updates,
    set_send_crash_reports,
)


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
        self._crash_reports_box = QCheckBox("Send crash reports")
        self._crash_reports_box.setToolTip(
            "When GitCrisp crashes, send the error and stack trace so it can be fixed.\n"
            "No repository contents or personal data; your home folder is replaced by ~."
        )
        self._crash_reports_box.setChecked(get_send_crash_reports())
        form.addRow(self._crash_reports_box)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        set_check_updates(self._check_updates_box.isChecked())
        send = self._crash_reports_box.isChecked()
        set_send_crash_reports(send)
        set_crash_reporting_enabled(send)
        super().accept()
