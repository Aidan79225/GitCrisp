"""Reusable chevron toggle button used by collapsible diff sections."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QToolButton


class _CollapseToggle(QToolButton):
    """Down/right chevron toggle.

    Emits state_changed(True) when expanded, False when collapsed.
    Compact (16x16), auto-raise so it sits flush in a header row.
    """

    state_changed = Signal(bool)

    def __init__(self, expanded: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(expanded)
        self.setAutoRaise(True)
        self.setFixedSize(QSize(16, 16))
        self.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.setCursor(Qt.PointingHandCursor)
        # Drop the QToolButton chrome on every state — the user only wants
        # the bare arrow, no surrounding border / hover background.
        self.setStyleSheet(
            "QToolButton { border: none; background: transparent; padding: 0; }"
            "QToolButton:hover { background: transparent; }"
            "QToolButton:pressed { background: transparent; }"
            "QToolButton:checked { background: transparent; }"
        )
        self.toggled.connect(self._on_toggle)

    def _on_toggle(self, checked: bool) -> None:
        self.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        self.state_changed.emit(checked)

    def is_expanded(self) -> bool:
        return self.isChecked()
