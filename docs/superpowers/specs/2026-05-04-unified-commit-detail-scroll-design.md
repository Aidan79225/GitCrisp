# Unified Commit-Detail Scroll — Design Spec

**Date:** 2026-05-04
**Author:** Aidan Wang (with Claude Opus 4.7)
**Status:** Approved for implementation planning

## Goal

Make the four sections of the commit-detail panel — state banner, commit info,
commit message, file list, diff content — feel like one continuously scrollable
column instead of three independent scroll surfaces (file list, diff content,
fixed top header). The user's mental model becomes "read this commit as one
page," matching the GitHub commit-page feel.

## Motivation

`DiffWidget` today composes a fixed top region (state banner + commit detail
row + commit message), then a `QSplitter(Qt.Vertical)` containing a file list
and a diff scroll area. Two independent scrollbars (file list, diff content)
sit inside the splitter, and the top region permanently consumes vertical
space. The user finds this fragmented — clicking a file scrolls in one region,
reading hunks scrolls in another, and the always-visible top region steals
diff height.

A previous "scroll-to-collapse" header (2026-04-17) was removed on 2026-04-25
in favour of "header always fully visible." This spec supersedes that direction
with a different one: rather than shrinking the header on scroll, allow it to
**scroll out of view naturally** as part of one unified scroll, while keeping
two specific regions sticky (state banner, file navigator).

## UX decisions (locked)

| # | Decision | Choice |
|---|---|---|
| 1 | Motivation | "Read it as one page" (GitHub-commit-page feel) |
| 2 | File-list role | Still filters the diff on click (today's behavior) |
| 3 | File-list height strategy | Sticky after scroll-past |
| 4 | Pinned shape | Horizontal pill strip (one pill per file + "All" pill) |
| 5 | Natural shape (scroll = 0) | Vertical list, transforms to pill strip when pinned |
| 6 | Auto-highlight pill on scroll | Yes (in "All" mode only) |
| 7 | File-switch scroll behavior | Scroll lands at start of diff section under the pill strip |
| – | State banner | Sticky too (pins above the pill strip) |
| – | Splitter | Removed — file list and diffs share the unified scroll |
| – | Implementation pattern | Reparenting on threshold (single navigator widget identity) |

## Architecture

Pure presentation-layer change. Domain (`Commit`, `FileStatus`), application
(queries — `get_commit_detail`, `get_file_diff`, `get_commit_files`,
`get_commit_diff_map`, `get_branches`), and infrastructure (pygit2 ops) are
untouched. All changes live under `git_gui/presentation/widgets/`.

### New widget tree

```
DiffWidget (QWidget)
├── outer QVBoxLayout
│   ├── _state_banner          ← always above scroll, never scrolls
│   ├── _pin_slot (QWidget)    ← receives _file_navigator when pinned
│   └── _scroll_area (QScrollArea, widget-resizable)
│       └── _scroll_content (QWidget, QVBoxLayout)
│           ├── _detail (CommitDetailWidget)         ← unchanged widget
│           ├── _msg_view (QPlainTextEdit)           ← unchanged widget
│           ├── _flow_slot (QWidget)                 ← receives _file_navigator when unpinned
│           └── _diff_container (QWidget, QVBoxLayout of file blocks)
```

The two slots (`_pin_slot`, `_flow_slot`) are stable parent containers used as
reparent destinations for the single `_file_navigator` instance. Only one slot
holds the navigator at any time; the other has an empty layout.

### Scroll surfaces

Two scroll surfaces survive:

1. The **outer unified vertical scroll** (`_scroll_area`).
2. An **internal horizontal scroll** inside the pill strip, used only when
   there are too many pills to fit the panel width. This is a separate axis,
   so it does not violate the "scroll together" intent.

The previous `_diff_scroll` (vertical scroll inside the splitter's bottom
half) and the splitter itself are removed.

## Components

### `FileNavigatorWidget` — new

Path: `git_gui/presentation/widgets/file_navigator.py`

Responsibility: present the commit's file list in two interchangeable shapes
(vertical list, horizontal pill strip) backed by one selection model.

**Public surface**

- Constructor takes the shared `DiffModel`. Owns its own `QItemSelectionModel`
  bound to that model.
- `set_mode(Mode.LIST | Mode.PILL)` flips an internal `QStackedLayout`.
- `set_active_file(path: str | None)` updates a "this is the visually active
  file" highlight on the pill strip and the list view, **without** firing
  selection-model changes. Used by auto-highlight on scroll.
- Re-exposes `currentChanged` and a `deselected` signal equivalent to today's
  `_file_view`'s wiring, so `DiffWidget`'s filter call sites stay the same.
- `set_model(model)` to support the existing `DiffModel.reload(...)` flow.

**Internal layout (QStackedLayout)**

- Index 0 — `_list_view`: `QListView` + `_FileDeltaDelegate` (lifted as-is
  from today's `diff.py`).
- Index 1 — `_pill_strip`: a `QWidget` whose layout is a `QHBoxLayout` of
  `QToolButton`s. The strip is wrapped in a `QScrollArea` configured for
  horizontal scrolling and `Qt.ScrollBarAsNeeded`. Pills are torn down and
  rebuilt on `DiffModel.modelReset`. The leftmost pill is the synthetic
  "All" pill (not in the model — its click calls
  `selection_model.clearSelection()`).

Both children share the navigator's single selection model. A click in either
fires `currentChanged` once.

### `DiffWidget` — modified

Path: `git_gui/presentation/widgets/diff.py`

What changes:

- `_file_view`, `_diff_scroll`, `_splitter` deleted.
- `_state_banner` is added directly to the outer `QVBoxLayout` above the
  scroll area (was already at the top of the inner layout — the change is
  that it is now a sibling of the scroll area, not a child).
- `_pin_slot` and `_flow_slot` (empty `QWidget`s with tight `QVBoxLayout`s)
  are added.
- `_scroll_area: QScrollArea` is created with `setWidgetResizable(True)` and
  given `_scroll_content` as its widget.
- `_scroll_content`'s layout holds, in order: `_detail`, `_msg_view`,
  `_flow_slot`, `_diff_container`.
- `_file_navigator: FileNavigatorWidget` is constructed once and added to
  `_flow_slot`.
- `_loader: ViewportBlockLoader` is re-pointed at `_scroll_area`. Logic
  unchanged.
- `_set_empty_state(empty)` toggles `_detail`, `_msg_view`,
  `_file_navigator`, and `_diff_container` (but not `_pin_slot` /
  `_flow_slot`, which always exist as containers).
- `_StickyPinController` is constructed and connected to
  `_scroll_area.verticalScrollBar().valueChanged`.

What is unchanged:

- `load_commit`, `_render_all_files`, `_render_single_file`, `_clear_blocks`,
  `_build_file_block`, `_realize_block`, `_build_skeleton_block`,
  `_refresh_submodule_paths`, the diff-fetch background thread, the
  state-banner abort/continue handlers.
- The `eventFilter` blocking mouse interaction on `_msg_view`.
- `set_buses`, `update_state_banner`, `_on_banner_abort`,
  `_on_banner_continue`, `_on_theme_changed`, `_restyle_themed_panels`.

The `_file_view` selection-signal wiring (`currentChanged.connect(...)`,
`deselected.connect(...)`) is re-attached to `_file_navigator` instead.

### `_StickyPinController` — new helper, internal to `DiffWidget`

Owns the pin/unpin state machine and threshold computation.

```
class _StickyPinController:
    HYSTERESIS_PX = 4

    def __init__(self, owner: DiffWidget): ...
    def attach(self): ...                      # wire up scrollbar, model signals
    def recompute_threshold(self) -> None: ...  # = _flow_slot.geometry().top()
    def force_unpin(self) -> None: ...          # used by load_commit error path

    # Triggers
    # - scrollbar.valueChanged → _on_scroll(value)
    # - DiffWidget.resizeEvent → recompute_threshold()
    # - DiffModel.modelReset   → recompute_threshold()
    # - load_commit success    → recompute_threshold() + _unpin (force start state)
    # - load_commit error      → force_unpin()
```

Reparenting (`_pin` / `_unpin`) brackets `setUpdatesEnabled(False) /
setUpdatesEnabled(True)` on `DiffWidget` to avoid flicker.

## Data flow

### Initial load — `DiffWidget.load_commit(oid)`

```
graph_panel.commit_selected(oid)
  → load_commit(oid)
    1. queries.get_commit_detail(oid)                     [unchanged]
    2. _detail.set_commit(commit, refs)                   [unchanged]
    3. _msg_view.setPlainText(msg); setFixedHeight(h)     [unchanged]
    4. queries.get_commit_files(oid)                      [unchanged]
       _diff_model.reload(files)
       (FileNavigatorWidget rebuilds pills from modelReset)
    5. _render_all_files(oid)                             [unchanged]
    6. _scroll_area.verticalScrollBar().setValue(0)       [new — was _diff_scroll]
    7. _StickyPinController.recompute_threshold()         [new]
    8. _StickyPinController.force_unpin()                 [new — guarantee start state]
```

Step 7 must happen after steps 3 and 4 (because `_msg_view`'s height and the
list-view's row count both affect `_flow_slot.geometry().top()`). Both are
synchronous, so a single `recompute_threshold()` after them is sufficient —
no event-loop round-trip.

### Filter on click

```
user clicks a list row  ┐
        OR              ├─→ _file_navigator.selection_model.currentChanged(idx, prev)
user clicks a pill      ┘
                          ↓
              DiffWidget._on_file_selected(idx)
                          ↓
              queries.get_file_diff(oid, path)
                          ↓
              _render_single_file(path, hunks)
                          ↓
              if pinned:
                  _scroll_area.verticalScrollBar()
                      .setValue(_diff_container.geometry().top())
              else:
                  (leave scroll where it is)
              [Q7(A) — when pinned, the pinned region stays
               pinned and the new file's first hunk is the
               topmost diff content. When unpinned, the user
               sees the start of the diff already (it's
               within their natural-flow viewport just below
               the vertical file list); yanking them to
               _diff_container.top() would push commit info
               and message offscreen unnecessarily.]
```

### Deselect / "All" pill click → unfilter

```
user clicks active list row again        ┐
        OR                               ├─→ _file_navigator.deselected
user clicks "All" pill (synthetic row)   ┘
                                            ↓
                            DiffWidget._on_file_deselected()
                                            ↓
                            _render_all_files(_current_oid)
                                            ↓
                            if pinned:
                                _scroll_area.verticalScrollBar()
                                    .setValue(_diff_container.geometry().top())
                            else:
                                (leave scroll where it is)
```

The pin-conditional scroll-reset rule applies symmetrically to both
filter-on and filter-off transitions: when pinned, the diff section's first
file is brought to the top of the diff viewport; when unpinned, the user's
scroll position is preserved.

### Pin / unpin transition

```
_scroll_area.verticalScrollBar().valueChanged(value)
  → _StickyPinController._on_scroll(value)
      if not pinned and value >= threshold:
          owner.setUpdatesEnabled(False)
          _flow_slot.layout().removeWidget(_file_navigator)
          _file_navigator.setParent(None)
          _pin_slot.layout().addWidget(_file_navigator)
          _file_navigator.set_mode(PILL)
          owner.setUpdatesEnabled(True)
          self._pinned = True
      elif pinned and value < threshold - HYSTERESIS_PX:
          (reverse, with set_mode(LIST))
          self._pinned = False
```

`HYSTERESIS_PX = 4`.

### Auto-highlight on scroll (All mode only)

```
_scroll_area.verticalScrollBar().valueChanged(value)
  → if not _file_navigator.selection_model.hasSelection() and pinned:
        active_path = _find_active_file_block(value)
        _file_navigator.set_active_file(active_path)
```

`_find_active_file_block(value)` linear-scans `_diff_container`'s child file
frames, returning the path of the frame whose `geometry().top() <=
viewport_top < geometry().top() + geometry().height()`. With ≤~50 files in a
typical commit, the linear cost is acceptable; no sorted index needed.

`set_active_file` updates a CSS-active class on the corresponding pill button
and calls `pill_h_scroll.ensureVisible(button.geometry())` to bring offscreen
pills into view. It does **not** fire selection-model changes — auto-highlight
is purely visual.

## State table

Pinned (yes/no) and Filtered (yes/no) are independent axes — four logical
states.

| Pinned | Filter | Pill strip | List view | Diff content |
|---|---|---|---|---|
| No | None | hidden (mode = LIST) | visible | all files (skeletons → real) |
| No | one file | hidden (mode = LIST) | visible, row selected | one file's hunks |
| Yes | None | visible, "All" highlighted; auto-highlight tracks scroll | hidden (still in `_flow_slot`, scrolled out of view) | all files |
| Yes | one file | visible, that file's pill highlighted; auto-highlight disabled | hidden | one file's hunks |

## Edge cases

- **Zero files** (e.g., empty merge commit): list view empty; pill strip has
  only the "All" pill. Pin/unpin still work.
- **Many files (>50)**: list-mode height grows linearly; user scrolls past it
  as expected. Pill strip overflows horizontally and uses its internal
  horizontal scroll. No new failure modes.
- **Long commit message**: `_msg_view.setFixedHeight(...)` already handles
  this; `recompute_threshold()` reads `_flow_slot.geometry().top()` after the
  message height settles.
- **One file**: pill strip has "All" + one pill; list view has one row.
- **Mid-drag scroll thrash**: hysteresis (4 px on the unpin direction) absorbs
  micro-jitter near the boundary. If profiling later shows pin/unpin
  thrashing during a fast drag, debounce via `QTimer.singleShot(0, ...)` to
  coalesce consecutive `valueChanged` events.
- **Window resize**: `resizeEvent` triggers `recompute_threshold()`. If the
  new threshold is now greater than the current scroll value, we unpin. If
  still less or equal, we stay pinned. The navigator does not move during
  resize itself — only the threshold target shifts.
- **Theme change while pinned**: existing `connect_widget(self,
  rebuild=...)` plumbing triggers a restyle on both `DiffWidget` and
  `FileNavigatorWidget` (which registers its own `rebuild=_restyle`).
  Pinning state is unaffected.

## Theming

Per `CLAUDE.md`, no hard-coded colors. The pill strip uses these MD3 tokens
from `presentation/theme/tokens.py`:

| Element | Token | Notes |
|---|---|---|
| Pill background (idle) | `surface_container_high` | Matches today's `_msg_view` / `_file_view` background |
| Pill background (active) | `primary` | Matches today's row-selected highlight in `_FileDeltaDelegate` |
| Pill border | `outline` | Matches today's `_file_view` border |
| Pill text (idle) | `on_surface` | |
| Pill text (active) | `on_primary` | Verified present in `tokens.py` |
| Delta dot color | `colors.status_color(delta)` | Existing helper |
| Pinned region bottom separator | `outline_variant` (1 px) | No `shadow` token in tokens.py — use a thin border instead |

The pill strip QSS is built in `FileNavigatorWidget._restyle()`, called on
construction and on `connect_widget(self, rebuild=self._restyle)`.

## Error handling

- `get_commit_detail` raises (e.g., commit was rebased away): unchanged from
  today — clear all sub-panels, log warning, return. **Additionally:** call
  `_StickyPinController.force_unpin()` so the next successful load starts
  with the navigator in `_flow_slot`.
- `get_file_diff` raises during a filter click: unchanged. Out of scope.
- `get_commit_diff_map` raises in the background worker: unchanged. The
  worker's `try/except` already swallows it and emits `{}`.

## Testing

### Unit — `tests/presentation/widgets/test_file_navigator.py` (new)

- `test_constructed_with_empty_model_has_only_all_pill`
- `test_set_mode_toggles_stacked_layout`
- `test_clicking_list_row_updates_shared_selection`
- `test_clicking_pill_updates_shared_selection`
- `test_clicking_all_pill_clears_selection`
- `test_set_active_file_highlights_without_changing_selection`
- `test_set_active_file_calls_ensure_visible_for_offscreen_pill`
- `test_model_reset_rebuilds_pill_strip`

### Unit — sticky-pin controller tests (in `test_diff_widget.py`)

- `test_threshold_equals_flow_slot_top_after_load`
- `test_pin_when_scroll_passes_threshold`
- `test_unpin_when_scroll_below_threshold_minus_hysteresis`
- `test_hysteresis_prevents_unpin_just_below_threshold`
- `test_resize_event_recomputes_threshold`
- `test_model_reset_recomputes_threshold`
- `test_load_error_forces_unpin`

### Unit — auto-highlight tests (in `test_diff_widget.py`)

- `test_auto_highlight_finds_file_under_viewport_top`
- `test_auto_highlight_disabled_while_filtered`
- `test_auto_highlight_disabled_while_unpinned`

### Unit — filter-click scroll behavior (in `test_diff_widget.py`)

- `test_filter_click_while_pinned_scrolls_to_diff_container_top`
- `test_filter_click_while_unpinned_does_not_change_scroll`
- `test_deselect_while_pinned_scrolls_to_diff_container_top`
- `test_deselect_while_unpinned_does_not_change_scroll`

### Modified existing tests in `test_diff_widget.py`

- `test_load_commit_shows_panels` — assertion shifts from `_splitter.isVisible()`
  to `_scroll_area.isVisible()` and `_file_navigator.isVisible()`.
- `test_load_commit_error_hides_panels` — same kind of substitution; also
  assert navigator reparented to `_flow_slot`.
- `test_set_buses_none_enters_empty_state` — assert `_scroll_area`,
  `_file_navigator`, `_detail`, `_msg_view` all hidden.
- `test_clear_blocks_clears_loader` — unchanged in spirit; `_loader` is now
  bound to `_scroll_area`.

### Integration (`pytest-qt`)

- `test_load_then_scroll_pins_then_click_filters_then_scroll_back_unpins`
- `test_resize_while_pinned_stays_consistent`

### Manual smoke test (in implementation plan)

- Real repo with a 5+-file commit and multi-line message.
- Verify scroll = 0 layout (state banner / commit info / message / vertical
  list / start of diff).
- Wheel-scroll slowly across the pin threshold; verify the vertical list
  disappears at the same instant the pill strip appears, with no flicker.
- Click a pill → diff filters; scroll lands so the file's first hunk is just
  under the pill strip.
- Click "All" → all-files diff returns; scroll through and verify the active
  pill tracks the file under the viewport top, including horizontal pill
  auto-scroll for offscreen pills.
- Trigger a merge or rebase; verify the state banner is sticky in both
  unpinned and pinned states.
- Resize the window in both states; verify no jank.

## Files changed

| Path | Action |
|---|---|
| `git_gui/presentation/widgets/file_navigator.py` | New |
| `git_gui/presentation/widgets/diff.py` | Modify (replace splitter/file_view/diff_scroll with unified scroll architecture; wire `_StickyPinController`) |
| `tests/presentation/widgets/test_file_navigator.py` | New |
| `tests/presentation/widgets/test_diff_widget.py` | Modify (substitute attribute names in surviving tests; add sticky-pin and auto-highlight tests) |

Untouched: domain (`entities.py`, `ports.py`), application (`commands.py`,
`queries.py`), infrastructure (pygit2 ops), `presentation/models/diff_model.py`,
`presentation/widgets/commit_detail.py`, `presentation/widgets/diff_block.py`,
`presentation/widgets/file_list_view.py` (its `FileListView` is reused inside
`FileNavigatorWidget`), `presentation/widgets/viewport_block_loader.py`,
`presentation/widgets/working_tree.py`, `presentation/main_window/right_panel.py`,
all theme files.

## Out of scope / non-goals

- Working-tree mode (the index-1 widget in `right_panel.py`'s stack) gets no
  unified-scroll treatment in this spec. If desired later, it deserves its own
  spec — its content (staged/unstaged groups, hunk staging buttons) interacts
  differently from the read-only commit view.
- No animation on the pin transition. The transition is instantaneous; if a
  fade or slide is wanted later, it can be layered on without changing the
  state machine.
- No keyboard shortcut to jump between files via the pill strip in this spec.
  Tab order may put the pills in the focus chain, but no `Ctrl+→` /
  `Alt+arrow` style nav is added here.
- No persistence of pin state across commits. Every `load_commit` resets the
  navigator to `_flow_slot` / mode = LIST and scroll to 0.
