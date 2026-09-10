# Collapsing Commit Header — Design

**Date:** 2026-04-17
**Status:** Proposed

## Goal

Let the commit info and commit message in `DiffWidget` collapse as the user scrolls through the diff hunks, reclaiming vertical space for code. The behavior follows Material Design 3's medium/large top-app-bar pattern — a smooth parallax shrink tied to scroll position, not an on/off toggle.

## Scope

- A new `CollapsingHeader` widget that wraps the existing `CommitDetailWidget` and commit-message `QPlainTextEdit`.
- Wiring in `DiffWidget` to drive the header's collapse progress from `_diff_scroll.verticalScrollBar().valueChanged`.
- Reset-to-expanded on commit switch.
- No changes to the working-tree panel, the state banner, or the file list.

## UX Decisions

| Concern | Decision |
|---|---|
| Collapse style | Parallax shrink — smooth, continuous, proportional to scroll position. |
| At full collapse | Commit info + message fully hidden (no pinned subject bar). |
| File list | Stays pinned. Does not participate in the collapse. |
| Trigger source | `_diff_scroll` vertical scroll position (position-based, not direction-based). |
| Collapse range | Maps `scroll = 0 → expanded_height` to `progress = 0.0 → 1.0`. Beyond that, progress stays at 1.0. |
| Snap | None. Header tracks scroll position directly. |
| State banner (merge/rebase) | Stays pinned above the header; never collapses. |
| On commit switch | Header resets to fully expanded (`progress = 0`). |
| Scroll too short to collapse | Short diffs don't produce a full collapse — acceptable; the user already sees everything. |

## Approach

One new presentation widget, `CollapsingHeader`, with a single narrow API:

```python
header.set_collapse_progress(p: float)  # p ∈ [0.0, 1.0]
```

The widget owns `CommitDetailWidget` and the commit-message `QPlainTextEdit` as children. Its own `maximumHeight` is interpolated from its natural expanded height down to zero as `p` goes from `0.0` to `1.0`.

`DiffWidget` constructs the header, places it in the vertical layout where `_detail` + `_msg_view` used to be, and connects `_diff_scroll.verticalScrollBar().valueChanged` to a handler that converts scroll value to progress.

This keeps the collapse math in one testable place (no Qt scroll area involved; just input progress → output height), leaves `DiffWidget` responsible only for the wiring, and doesn't touch the splitter, the file list, the scroll area, or the loader.

## Architecture & files touched

**New files:**

```
git_gui/
└── presentation/widgets/
    └── collapsing_header.py   # CollapsingHeader widget

tests/
└── presentation/widgets/
    └── test_collapsing_header.py
```

**Modified files:**

```
git_gui/presentation/widgets/diff.py    # replace inline _detail + _msg_view with CollapsingHeader
```

**No changes to:** domain, application, infrastructure, theme tokens, QSS template, `commit_detail.py`, `file_list_view.py`, `viewport_block_loader.py`, `working_tree.py`.

## `collapsing_header.py`

```python
# git_gui/presentation/widgets/collapsing_header.py
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget
from git_gui.presentation.widgets.commit_detail import CommitDetailWidget


class CollapsingHeader(QWidget):
    """Vertical container for commit detail + commit message whose maximum
    height can be driven from 0 to its natural expanded height via
    `set_collapse_progress(p)` where `p=0.0` is fully expanded and `p=1.0`
    is fully collapsed."""

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

    def set_expanded_height(self, h: int) -> None:
        """Called by the owner whenever the natural expanded height changes
        (e.g. after a new commit loads and the message height is recomputed)."""
        self._expanded_height = max(0, int(h))
        self._apply()

    def expanded_height(self) -> int:
        return self._expanded_height

    def set_collapse_progress(self, p: float) -> None:
        """Clamp to [0.0, 1.0] and re-apply the max height."""
        self._progress = max(0.0, min(1.0, float(p)))
        self._apply()

    def collapse_progress(self) -> float:
        return self._progress

    def _apply(self) -> None:
        remaining = int(round(self._expanded_height * (1.0 - self._progress)))
        self.setMaximumHeight(remaining)
        # setFixedHeight would also work, but setMaximumHeight cooperates with
        # the parent layout's natural sizing policy.
        self.setMinimumHeight(0)
```

**Notes:**
- The header is *framework-light*: no animation timer, no scroll listening. It's a pure input-to-size mapping. All dynamic behavior lives in `DiffWidget`, which decides when to call `set_collapse_progress`.
- `set_expanded_height` is called every time the message height changes (once per commit load).
- `setMaximumHeight(0)` with `setMinimumHeight(0)` is enough to hide the widget. Qt still lays out the widget but gives it no vertical space.

## `diff.py` integration

**1. Replace inline construction** at `diff.py:111-125`. The `CommitDetailWidget` and `QPlainTextEdit` are still constructed the same way, but they become children of a `CollapsingHeader` instead of being added directly to the layout.

```python
self._detail = CommitDetailWidget()
self._detail.setAutoFillBackground(True)

self._msg_view = QPlainTextEdit()
self._msg_view.setReadOnly(True)
self._msg_view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
self._msg_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
self._msg_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
self._msg_view.viewport().installEventFilter(self)
self._msg_view.document().setDocumentMargin(12)
font = self._msg_view.font()
font.setFamily("Courier New")
self._msg_view.setFont(font)

self._header = CollapsingHeader(self._detail, self._msg_view)
```

**2. Update the outer layout** at `diff.py:157-164`:

```python
layout = QVBoxLayout(self)
layout.setContentsMargins(12, 8, 12, 8)
layout.setSpacing(8)
layout.addWidget(self._state_banner, 0)
layout.addWidget(self._header, 0)         # was: _detail + _msg_view
layout.addWidget(self._splitter, 1)
layout.addStretch()
```

**3. Drive collapse from scroll position.** Add to `__init__`, after `self._loader` is built:

```python
self._diff_scroll.verticalScrollBar().valueChanged.connect(
    self._on_diff_scrolled
)
```

And the handler:

```python
def _on_diff_scrolled(self, value: int) -> None:
    expanded = self._header.expanded_height()
    if expanded <= 0:
        return
    progress = value / expanded
    self._header.set_collapse_progress(progress)
```

**4. Update expanded-height on commit load.** Right after the existing `setFixedHeight` at `diff.py:292`, add:

```python
self._msg_view.setFixedHeight(msg_h)           # unchanged existing line
# Both children have had setFixedHeight called, so .maximumHeight() is the
# authoritative natural height and is available synchronously.
detail_h = self._detail.maximumHeight()
spacing = self._header.layout().spacing()
self._header.set_expanded_height(detail_h + msg_h + spacing)
# Reset scroll to top on every commit load; valueChanged will fire and zero
# the collapse progress as a side-effect.
self._diff_scroll.verticalScrollBar().setValue(0)
self._header.set_collapse_progress(0.0)        # defensive; no-op if already 0
```

Why `setValue(0)` explicitly: after `_clear_blocks` + re-render, the scrollbar's value may or may not reset to 0 depending on content height transitions. Forcing it removes the ambiguity.

**5. Reset on error / clear.** The error path at `diff.py:269-277` calls `_set_empty_state(True)`, which hides the header. Also call `self._header.set_collapse_progress(0.0)` there so the next successful commit load starts clean.

**6. Update `_set_empty_state`** to hide/show the header in place of the two old widgets:

```python
def _set_empty_state(self, empty: bool) -> None:
    self._header.setVisible(not empty)
    self._splitter.setVisible(not empty)
```

**7. Update `_restyle_themed_panels`** — no change in behavior; `_detail` and `_msg_view` still take the same stylesheets. The header itself needs no stylesheet.

## Interaction details

- **State banner stays pinned.** It is above `_header` in the vertical layout; nothing changes its height.
- **File list stays pinned.** It is inside `_splitter`, which is a sibling of `_header`. The splitter's sizing is unaffected.
- **Splitter resize still works.** User can still drag the splitter between file list and diff — independent of header collapse.
- **Scrollbar coupling.** The scroll bar is the single source of truth for collapse progress. Any input that moves the scrollbar (wheel, drag, keyboard, viewport loader scroll-to-hunk) drives the collapse uniformly.
- **Wheel over the header itself.** The header has no scroll area; wheel events bubble up and don't move the diff scroll bar from the header area. This is consistent with how the widget behaves today.
- **Commit switch reset.** `load_commit` explicitly calls `verticalScrollBar().setValue(0)` and `_header.set_collapse_progress(0.0)`. The former triggers `valueChanged`, which re-runs the handler and forces progress back to 0 regardless of prior state; the latter is a belt-and-suspenders no-op for the case where the scrollbar was already at 0.

## Edge cases

- **Empty commit message.** `msg_h` is small (~line_h + 2*margin); expanded height is mostly `_detail` height. Collapse still works; just over a smaller range.
- **Very long commit message.** Message height can be large; expanded height is large; scroll range used for collapse is long. This is by design — larger headers take more scroll to collapse.
- **Short diff (no scroll needed).** `valueChanged` never fires; progress stays `0.0`. Correct.
- **Scroll value > expanded height.** `progress` clamps to `1.0` inside `set_collapse_progress`. Header stays hidden.
- **Theme change.** No header code path cares about theme. Children (`_detail`, `_msg_view`) handle it as today.
- **Commit load failure.** The error path at `diff.py:269-277` calls `_set_empty_state(True)`, which hides the header. No stale progress matters.
- **Resize of the DiffWidget.** The header's expanded height does not change on widget resize (message heights are line-count driven, not width driven, because `_msg_view` line-wraps at widget width but its `setFixedHeight` is computed from line count). If this turns out to misrepresent wrapped-line heights, it can be revisited — same gotcha exists today.

## Performance

- `valueChanged.connect(_on_diff_scrolled)` fires on every scrollbar value change. The handler is O(1): one division, one `setMaximumHeight` call. No measurable cost even on fast scrolls.
- No animation timers, no threads, no caching. The widget simply reacts.

## Testing

**`tests/presentation/widgets/test_collapsing_header.py`** (pytest-qt):

- `set_expanded_height(200)` + `set_collapse_progress(0.0)` → `maximumHeight() == 200`.
- `set_collapse_progress(1.0)` → `maximumHeight() == 0`.
- `set_collapse_progress(0.5)` → `maximumHeight() == 100`.
- `set_collapse_progress(-0.3)` → clamps to `0.0`; `maximumHeight() == 200`.
- `set_collapse_progress(2.0)` → clamps to `1.0`; `maximumHeight() == 0`.
- `set_expanded_height(0)` → `maximumHeight() == 0` regardless of progress.
- Changing expanded height re-applies current progress: after `set_collapse_progress(0.5)` then `set_expanded_height(400)` → `maximumHeight() == 200`.
- Children (`CommitDetailWidget`, `QPlainTextEdit`) are reachable via the header's layout, proving they were reparented correctly.

**`tests/presentation/widgets/test_diff_collapse_wiring.py`** (pytest-qt, thin integration):

- Load a commit with a short message → scroll the diff scroll area → verify `_header.collapse_progress()` increases.
- Scroll back to top → progress returns to `0.0`.
- Switch commits → progress resets to `0.0` even if the user was mid-scroll.
- With an empty state (no commit loaded), `_header.isVisible() is False`.

No end-to-end GUI smoke test; manual verification after implementation.

## Out of scope

- Direction-based ("enterAlways") collapse — scrolling up from the middle of the diff re-expands the header.
- Snap-to-state when scrolling stops partway.
- Pinned short-hash + subject strip at full collapse.
- Applying the same behavior to the working-tree panel's hunk diff.
- Animated transitions on commit switch (the reset is instant).
- Making the collapse range user-configurable.
- Collapsing the file list.
