# git_gui/presentation/widgets/collapsing_header.py
from __future__ import annotations
from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

from git_gui.presentation.widgets.commit_detail import CommitDetailWidget


class CollapsingHeader(QWidget):
    """Vertical container for commit detail + commit message whose maximum
    height can be driven from 0 to its natural expanded height via
    `set_collapse_progress(p)` where `p=0.0` is fully expanded and `p=1.0`
    is fully collapsed.

    The widget has no scroll awareness of its own. The owner connects
    whichever scroll source it likes and calls `set_collapse_progress`.
    """

    def __init__(
        self,
        detail: CommitDetailWidget,
        msg_view: QPlainTextEdit,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._detail = detail
        self._msg_view = msg_view
        self._expanded_height = 0
        self._progress = 0.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(detail)
        layout.addWidget(msg_view)

        self._apply()

    # ── Natural expanded size ────────────────────────────────────────────
    def set_expanded_height(self, h: int) -> None:
        """Called by the owner whenever the natural expanded height changes
        (e.g. after a new commit loads and the message height is recomputed)."""
        self._expanded_height = max(0, int(h))
        self._apply()

    def expanded_height(self) -> int:
        return self._expanded_height

    # ── Collapse progress ────────────────────────────────────────────────
    def set_collapse_progress(self, p: float) -> None:
        """Clamp to [0.0, 1.0] and re-apply the max height."""
        self._progress = max(0.0, min(1.0, float(p)))
        self._apply()

    def collapse_progress(self) -> float:
        return self._progress

    # ── Internal ─────────────────────────────────────────────────────────
    def _apply(self) -> None:
        remaining = int(round(self._expanded_height * (1.0 - self._progress)))
        self.setMinimumHeight(0)
        self.setMaximumHeight(remaining)
