"""IdentityDialog — inline prompt for missing git user.name / user.email."""

from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from git_gui.presentation.bus import CommandBus, QueryBus

logger = logging.getLogger(__name__)


class IdentityDialog(QDialog):
    """Modal prompt for git user.name / user.email when missing.

    Pre-fills any value that's already set even if the other is missing.
    Ok is disabled until both fields are non-empty after stripping.
    """

    def __init__(
        self,
        initial_name: str | None,
        initial_email: str | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set Git Identity")
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Your git user.name and user.email aren't configured for this repo.\n"
                "Set them now to commit:"
            )
        )

        form = QFormLayout()
        self._name_edit = QLineEdit(initial_name or "")
        self._email_edit = QLineEdit(initial_email or "")
        form.addRow("Name:", self._name_edit)
        form.addRow("Email:", self._email_edit)
        layout.addLayout(form)

        self._global_check = QCheckBox("Save globally for all repos (--global)")
        layout.addWidget(self._global_check)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._ok_btn = buttons.button(QDialogButtonBox.Ok)

        self._name_edit.textChanged.connect(self._update_ok)
        self._email_edit.textChanged.connect(self._update_ok)
        self._update_ok()

    def _update_ok(self) -> None:
        self._ok_btn.setEnabled(
            bool(self._name_edit.text().strip()) and bool(self._email_edit.text().strip())
        )

    def values(self) -> tuple[str, str, bool]:
        return (
            self._name_edit.text().strip(),
            self._email_edit.text().strip(),
            self._global_check.isChecked(),
        )


def ensure_identity(parent: QWidget, queries: QueryBus, commands: CommandBus) -> bool:
    """Prompt for git identity if not yet configured.

    Returns True if identity is already set, or the user successfully
    set it via the dialog. Returns False if the user cancelled or
    saving failed; the caller decides any error messaging.
    """
    name, email = queries.get_identity.execute()
    if name and email:
        return True
    dlg = IdentityDialog(name, email, parent=parent)
    if dlg.exec() != QDialog.Accepted:
        return False
    new_name, new_email, global_ = dlg.values()
    try:
        commands.set_identity.execute(new_name, new_email, global_)
    except Exception:
        logger.exception("Failed to save git identity")
        return False
    return True
