"""Reusable viewport-driven lazy block loader.

Manages the state machine for skeleton-block realization: tracks which
file blocks exist, which have been realized, debounces scroll events,
and realizes one block per event-loop tick when it enters the viewport.

Used by both DiffWidget (commit view) and HunkDiffWidget (working tree)
to avoid duplicating the viewport-intersection + stale-frame logic.
"""
from __future__ import annotations
from typing import Any, Callable

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget


class ViewportBlockLoader:
    """Lazy block loader driven by scroll-area viewport intersection.

    Parameters
    ----------
    scroll_area:
        The QScrollArea whose viewport is used for intersection checks.
    realize_fn:
        ``realize_fn(path, inner_layout, skeleton_or_none, diff_entry)``
        is called when a block enters the viewport and needs to be
        realized. The widget provides this callback to do domain-specific
        hunk rendering.
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

        scroll_area.verticalScrollBar().valueChanged.connect(
            lambda _: self._scroll_timer.start()
        )

    def set_blocks(
        self, block_refs: list[tuple[str, QFrame, QVBoxLayout, QWidget | None]]
    ) -> None:
        """Register skeleton blocks. Resets loaded-paths and diff map."""
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

    def clear(self) -> None:
        """Reset all state. Call from the widget's layout-clear method."""
        self._block_refs = []
        self._loaded_paths = set()
        self._diff_map = {}

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _check_viewport(self) -> None:
        """Realize the first visible unloaded block, then reschedule.

        Only one block per call — after realization the layout shifts,
        so we reschedule via ``QTimer.singleShot(0, ...)`` to let Qt
        process the growth before re-checking.

        Wraps frame access in ``try/except RuntimeError`` to handle
        stale C++ references from frames deleted by a newer load.
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
