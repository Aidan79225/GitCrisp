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

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget


class ViewportBlockLoader:
    """Lazy block loader driven by scroll-area viewport intersection.

    `realize_fn` is what a block actually becomes — the one thing the two
    callers do differently.
    """

    def __init__(
        self,
        scroll_area: QScrollArea,
        realize_fn: Callable[[str, QVBoxLayout, QWidget | None, Any], None],
    ) -> None:
        self._scroll_area = scroll_area
        self._realize_fn = realize_fn
        self._block_refs: list[tuple[str, QFrame, QVBoxLayout, QWidget | None]] = []
        self._loaded_paths: set[str] = set()
        self._diff_map: dict[str, Any] = {}

        self._scroll_timer = QTimer()
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(50)
        self._scroll_timer.timeout.connect(self._check_viewport)

        scroll_area.verticalScrollBar().valueChanged.connect(lambda _: self._scroll_timer.start())

    def set_blocks(self, block_refs: list[tuple[str, QFrame, QVBoxLayout, QWidget | None]]) -> None:
        self._block_refs = list(block_refs)
        self._loaded_paths = set()
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
        self._loaded_paths = set()
        self._diff_map = {}

    # Private

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
            vp_rect = viewport.rect()
        except RuntimeError:
            return
        for path, frame, inner, skeleton in list(self._block_refs):
            if path in self._loaded_paths:
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
                self._loaded_paths.add(path)
                QTimer.singleShot(0, self._check_viewport)
                return
