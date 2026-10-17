from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSizePolicy


class ElidingLabel(QLabel):
    """A status line that gives way to the controls beside it.

    A QLabel reports its full text width as its *minimum*, so a stretch factor
    cannot shrink it: below the header's natural width the layout had nowhere
    to take the space from and pushed the controls beside it off the edge, or
    held the whole pane at the width of a long path. A status line is the part
    of a header that can afford to lose characters, so it is the part that
    gives.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def setText(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)  # the whole line stays reachable when it is cut
        self._elide()

    def full_text(self) -> str:
        """The text as set, whatever is currently painted."""
        return self._full

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        QLabel.setText(self, self.fontMetrics().elidedText(self._full, Qt.ElideRight, self.width()))
