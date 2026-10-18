"""Realises a file's diff block only once it scrolls into view.

Building every block up front is what made a large commit — or a working tree
holding thousands of changes — freeze the window, so blocks start as skeletons
and only the ones the user can actually see are ever built.

Shared by the commit view and the working-tree view, which differ in what a
realised block contains and in nothing else.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QFrame, QScrollArea, QVBoxLayout, QWidget

# A file's block: its path, its frame, the layout hunks go into, and the
# skeleton standing in for them until it is realised.
BlockRef = tuple[str, QFrame, QVBoxLayout, QWidget | None]


class DiffMapSignals(QObject):
    """Brings a diff map fetched off the UI thread back to it.

    It carries the generation of the blocks the fetch was started for, so a
    map that lands after those blocks were replaced can be told apart.
    """

    done = Signal(object, int)  # diff map keyed by path, blocks generation


class ViewportBlockLoader(QObject):
    """Lazy block loader driven by scroll-area viewport intersection.

    `realize_fn` is what a block actually becomes — the one thing the two
    callers do differently.
    """

    def __init__(
        self,
        scroll_area: QScrollArea,
        realize_fn: Callable[[str, QVBoxLayout, QWidget | None, Any], None],
    ) -> None:
        super().__init__()
        self._scroll_area = scroll_area
        self._realize_fn = realize_fn
        self._block_refs: list[BlockRef] = []
        # Positions in _block_refs, not paths: a commit that changes a file's
        # type lists the path twice, and tracking by path left the second
        # block a skeleton for good.
        self._realized: set[int] = set()
        self._diff_map: dict[str, Any] = {}

        self._scroll_timer = QTimer()
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(50)
        self._scroll_timer.timeout.connect(self._check_viewport)

        scroll_area.verticalScrollBar().valueChanged.connect(lambda _: self._scroll_timer.start())
        scroll_area.viewport().installEventFilter(self)

    def set_blocks(self, block_refs: list[BlockRef]) -> None:
        self._block_refs = list(block_refs)
        self._realized = set()
        self._diff_map = {}

    def set_diff_map(self, diff_map: dict[str, Any]) -> None:
        """Store the fetched diff data and schedule the first viewport check.

        Deferred one event-loop tick so Qt can lay out the skeletons before
        we ask which blocks are visible.
        """
        self._diff_map = diff_map
        QTimer.singleShot(0, self._check_viewport)

    def check_viewport(self) -> None:
        """Re-run the viewport intersection check on the next debounce tick.

        Useful when a layout change (e.g., a file diff block collapsing or
        expanding) shifts which blocks are visible without firing a
        scrollbar valueChanged signal.
        """
        self._scroll_timer.start()

    def clear(self) -> None:
        self._block_refs = []
        self._realized = set()
        self._diff_map = {}

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        # Blocks that arrived while the pane was hidden are still waiting.
        if event.type() == QEvent.Show:
            self._scroll_timer.start()
        return False

    # Private

    def _settle_layout(self) -> None:
        """Run the layout Qt has pending, so block positions are current.

        Building a block grows it, and the next check runs one event-loop turn
        later, which can be before Qt has laid the grown block out. Measured
        then, the blocks below still sit where their skeletons were, on screen,
        and are built although nothing can see them.
        """
        QApplication.sendPostedEvents(None, QEvent.LayoutRequest)
        content = self._scroll_area.widget()
        if content is not None and content.layout() is not None:
            content.layout().activate()

    def _check_viewport(self) -> None:
        """Realize the first visible unloaded block, then reschedule.

        One block per call: realising it grows the layout and moves everything
        below, so which block is visible next cannot be known until Qt has laid
        this one out.

        RuntimeError is a frame a newer load already deleted — the Python
        wrapper outlives the C++ widget, and touching it raises.
        """
        if not self._block_refs or not self._diff_map:
            return
        try:
            viewport = self._scroll_area.viewport()
            self._settle_layout()
            vp_rect = viewport.rect()
            # A pane the window is not showing (a page the stack keeps behind
            # another) is never laid out: every new frame stays at (0, 0),
            # reads as on screen, and the whole commit would be built.
            if not viewport.isVisible():
                return
        except RuntimeError:
            return
        for index, (path, frame, inner, skeleton) in enumerate(list(self._block_refs)):
            if index in self._realized:
                continue
            if frame is None:
                continue
            try:
                top_left = frame.mapTo(viewport, QPoint(0, 0))
                frame_rect = frame.rect().translated(top_left)
            except RuntimeError:
                continue
            if frame_rect.intersects(vp_rect):
                entry = self._diff_map.get(path)
                if entry is not None:
                    self._realize_fn(path, inner, skeleton, entry)
                    _show_what_was_added(inner)
                self._realized.add(index)
                QTimer.singleShot(0, self._check_viewport)
                return


def _show_what_was_added(inner: QVBoxLayout) -> None:
    """Show the widgets a block was just given, so they count in its layout now.

    Qt shows a widget added to a visible layout on a later event-loop turn,
    and until then the layout treats it as empty: a block that just received
    its hunks is sized as a bare header, and the check that follows reads the
    blocks below as on screen. Widgets the block hid on purpose stay hidden.
    """
    for i in range(inner.count()):
        widget = inner.itemAt(i).widget()
        if (
            widget is not None
            and widget.isHidden()
            and not widget.testAttribute(Qt.WA_WState_ExplicitShowHide)
        ):
            widget.show()
