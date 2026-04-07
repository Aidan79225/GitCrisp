"""ThemeDialog — pick System/Light/Dark/Custom theme.

Custom mode (Task 3) opens a colour token editor. This file currently
contains the mode radios + Apply/Cancel/Reset wiring; the custom panel
is a placeholder.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from git_gui.presentation.theme import get_theme_manager


_MODES: list[tuple[str, str]] = [
    ("system", "System"),
    ("dark",   "Dark"),
    ("light",  "Light"),
    ("custom", "Custom"),
]


class ThemeDialog(QDialog):
    """Modal dialog for choosing the active theme."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Theme")
        self.setModal(True)
        self.setMinimumSize(520, 400)

        self._mgr = get_theme_manager()
        layout = QVBoxLayout(self)

        # --- Mode radios ---
        mode_group = QGroupBox("Mode")
        mode_layout = QHBoxLayout(mode_group)
        self._mode_buttons = QButtonGroup(self)
        self._mode_buttons.setExclusive(True)
        for mode, label in _MODES:
            radio = QRadioButton(label)
            radio.setProperty("mode", mode)
            radio.setChecked(self._mgr.mode == mode)
            self._mode_buttons.addButton(radio)
            mode_layout.addWidget(radio)
            radio.toggled.connect(self._on_mode_radio_toggled)
        layout.addWidget(mode_group)

        # --- Custom panel (placeholder; populated by Task 3) ---
        self._custom_panel = QGroupBox("Custom")
        custom_layout = QVBoxLayout(self._custom_panel)
        custom_layout.addWidget(QLabel("Custom editor — populated in Task 3."))
        self._custom_panel.setEnabled(self._selected_mode() == "custom")
        layout.addWidget(self._custom_panel)

        layout.addStretch()

        # --- Buttons ---
        buttons = QDialogButtonBox(
            QDialogButtonBox.Apply | QDialogButtonBox.Cancel | QDialogButtonBox.Reset
        )
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self._on_apply)
        buttons.button(QDialogButtonBox.Cancel).clicked.connect(self._on_cancel)
        buttons.button(QDialogButtonBox.Reset).clicked.connect(self._on_reset)
        layout.addWidget(buttons)

    def _selected_mode(self) -> str:
        for radio in self._mode_buttons.buttons():
            if radio.isChecked():
                return radio.property("mode")
        return self._mgr.mode

    def _on_mode_radio_toggled(self, _checked: bool) -> None:
        self._custom_panel.setEnabled(self._selected_mode() == "custom")

    def _on_apply(self) -> None:
        mode = self._selected_mode()
        # Custom mode write (Task 3) happens before set_mode so the file
        # exists when ThemeManager loads it.
        self._mgr.set_mode(mode)
        self.accept()

    def _on_cancel(self) -> None:
        self.reject()

    def _on_reset(self) -> None:
        # Task 3 reloads dark defaults into the editor here.
        pass
