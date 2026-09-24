"""About dialog: tells the user which GitCrisp build they are running."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from git_gui.observability import _get_version
from git_gui.presentation.theme import get_theme_manager

REPO_URL = "https://github.com/Aidan79225/GitCrisp"


def version_text(version: str) -> str:
    """The version line shown to the user.

    ``_get_version()`` reports ``"unknown"`` for a run from a checkout, where
    no release tag was baked in; "unknown" reads like a fault, so name it for
    what it is.
    """
    if version == "unknown":
        return "Version: dev build"
    return f"Version: {version.lstrip('v')}"


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About GitCrisp")
        self.setModal(True)

        theme = get_theme_manager().current
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.spacing.lg, theme.spacing.lg, theme.spacing.lg, theme.spacing.md
        )
        layout.setSpacing(theme.spacing.sm)

        title = QLabel("GitCrisp")
        title.setFont(theme.typography.as_qfont("title_large"))
        layout.addWidget(title)

        # Selectable so a user filing a bug can copy it verbatim.
        self._version_label = QLabel(version_text(_get_version()))
        self._version_label.setFont(theme.typography.as_qfont("body_medium"))
        self._version_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._version_label)

        link = QLabel(f'<a href="{REPO_URL}">{REPO_URL}</a>')
        link.setFont(theme.typography.as_qfont("body_small"))
        link.setStyleSheet(f"color: {theme.colors.on_surface_variant};")
        link.setOpenExternalLinks(True)
        layout.addWidget(link)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
