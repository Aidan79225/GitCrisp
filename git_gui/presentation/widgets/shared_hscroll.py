# git_gui/presentation/widgets/shared_hscroll.py
"""One horizontal scrollbar for a pane made of many hunk editors.

Every hunk is its own fixed-height QPlainTextEdit with both scrollbars hidden.
That is right for the vertical axis — the pane's QScrollArea owns it, and a
per-hunk bar would eat into a height computed from the line count — but it left
the horizontal axis with no visible control at all. The content still scrolls:
a trackpad swipe or Shift+wheel moves one hunk sideways, on its own, with
nothing to say the text continued and nothing bringing the other hunks along.

So the bar belongs to the pane, not to each hunk. One bar drives every editor,
and follows any of them when something scrolls one directly.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QPlainTextEdit, QScrollBar, QWidget

# Set on an editor once its scrollbar is wired up. Kept on the widget rather
# than in a list here because the widget is what knows when it dies: blocks are
# torn down with deleteLater, and a list of our own would go on holding editors
# whose C++ side is gone — touching one of those raises.
_BOUND = "_shared_hscroll_bound"


class SharedHScroll(QObject):
    """Keeps one QScrollBar and a pane's hunk editors in step.

    The editors are looked up on each use rather than cached: they arrive over
    time as blocks realize lazily, a theme change replaces them, and a clear
    destroys them. findChildren never hands back a destroyed widget, which a
    cache cannot promise — and it costs ~100us over sixty editors, well under
    a frame even while a drag is in flight.
    """

    def __init__(self, bar: QScrollBar, container: QWidget, parent=None) -> None:
        super().__init__(parent)
        self._bar = bar
        self._container = container
        # The bar and the editors drive each other, so a naive connection would
        # bounce. Only the first move of a round is allowed to propagate.
        self._syncing = False

        bar.setOrientation(Qt.Horizontal)
        bar.setVisible(False)
        bar.valueChanged.connect(self._on_bar_moved)

    def _editors(self) -> list[QPlainTextEdit]:
        return self._container.findChildren(QPlainTextEdit)

    def refresh(self) -> None:
        """Re-measure how far the widest hunk reaches, and wire up new ones."""
        editors = self._editors()
        for editor in editors:
            if not editor.property(_BOUND):
                editor.setProperty(_BOUND, True)
                editor.horizontalScrollBar().valueChanged.connect(self._on_editor_moved)
                editor.destroyed.connect(self._on_editor_destroyed)

        reach = max((e.horizontalScrollBar().maximum() for e in editors), default=0)
        self._bar.setRange(0, reach)
        self._bar.setPageStep(max(self._container.width(), 1))
        # One character, so arrow keys and track clicks move by something that
        # lines up with the text.
        step = editors[0].fontMetrics().horizontalAdvance("0") if editors else 1
        self._bar.setSingleStep(max(step, 1))
        # Nothing overflows: the bar would only be a strip of dead chrome.
        self._bar.setVisible(reach > 0)
        if reach == 0 and self._bar.value():
            self._bar.setValue(0)

    def _on_editor_destroyed(self, _obj=None) -> None:
        """Re-measure once the teardown has finished.

        Deferred, because clearing a pane destroys its editors one after
        another and this fires part-way through: measuring now would read a
        half-emptied pane, and would reach for siblings already destroyed.
        """
        QTimer.singleShot(0, self.refresh)

    def _on_bar_moved(self, value: int) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            for editor in self._editors():
                editor.horizontalScrollBar().setValue(value)
        finally:
            self._syncing = False

    def _on_editor_moved(self, value: int) -> None:
        """A trackpad or Shift+wheel moved one hunk; bring the rest with it."""
        if self._syncing:
            return
        self._syncing = True
        try:
            self._bar.setValue(value)
            for editor in self._editors():
                editor.horizontalScrollBar().setValue(value)
        finally:
            self._syncing = False
