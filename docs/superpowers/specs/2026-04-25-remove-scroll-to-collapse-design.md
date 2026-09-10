# Remove Scroll-to-Collapse Commit Header — Design

**Date:** 2026-04-25
**Status:** Proposed

## Goal

Remove the scroll-to-collapse behavior on the commit info + commit message header in `DiffWidget`. After this change, the header is always fully visible above the file list and diff, regardless of how far the user has scrolled through the diff hunks. No replacement behavior (no manual toggle, no splitter handle) — the decision is Option A: header stays fixed at full size.

This reverts the feature introduced by `docs/superpowers/specs/2026-04-17-collapsing-commit-header-design.md`.

## Scope

- Delete the `CollapsingHeader` widget and its unit-test file.
- Unwind the header wrapper in `DiffWidget`: add `_detail` and `_msg_view` directly to the outer vertical layout where the wrapper used to sit.
- Remove scroll → collapse wiring (`valueChanged.connect`, `_on_diff_scrolled`).
- Remove `set_expanded_height` / `set_collapse_progress` calls in `load_commit` (both happy and error paths).
- Remove the scroll-top reset in `load_commit` that only existed to drive the collapse handler.
- Update `_set_empty_state` to toggle `_detail` and `_msg_view` directly instead of the wrapper.
- Delete the five collapse-related tests in `test_diff_widget.py`.
- Remove the single README bullet that advertised the collapse feature.
- Leave the historical 2026-04-17 spec/plan docs in place as a record of what was tried and reverted.

## Out of Scope

- Any replacement UX for reclaiming vertical space (manual toggle, splitter, sticky short-hash bar, etc.).
- Changes to the working-tree panel, the state banner, the file list, the viewport block loader, or the splitter.
- Changes to domain, application, infrastructure, theme tokens, or QSS.
- Deleting the 2026-04-17 design/plan docs.

## Files Changed

**Delete:**

- `git_gui/presentation/widgets/collapsing_header.py`
- `tests/presentation/widgets/test_collapsing_header.py`

**Modify:**

- `git_gui/presentation/widgets/diff.py`
- `tests/presentation/widgets/test_diff_widget.py`
- `README.md`

**Untouched:** everything else.

## `diff.py` Changes (Detailed)

Line numbers refer to the file as it stands at the start of this change.

**Imports (line 15):** remove `from git_gui.presentation.widgets.collapsing_header import CollapsingHeader`.

**Header construction (line 128):** remove `self._header = CollapsingHeader(self._detail, self._msg_view)`. The `_detail` (lines 113–114) and `_msg_view` (lines 117–126) constructions stay exactly as they are — they remain first-class attributes of `DiffWidget`.

**Scroll handler wiring (lines 144–146):** remove

```python
self._diff_scroll.verticalScrollBar().valueChanged.connect(
    self._on_diff_scrolled
)
```

**Outer layout (line 167):** replace `layout.addWidget(self._header, 0)` with

```python
layout.addWidget(self._detail, 0)
layout.addWidget(self._msg_view, 0)
```

Order and position relative to `self._state_banner` (above) and `self._splitter` (below) are unchanged, so the visual layout stays identical to the expanded state before the removal.

**`_set_empty_state` (lines 181–184):** replace

```python
def _set_empty_state(self, empty: bool) -> None:
    self._header.setVisible(not empty)
    self._splitter.setVisible(not empty)
```

with

```python
def _set_empty_state(self, empty: bool) -> None:
    self._detail.setVisible(not empty)
    self._msg_view.setVisible(not empty)
    self._splitter.setVisible(not empty)
```

**`_on_diff_scrolled` method (lines 233–239):** delete the entire method.

**Error path in `load_commit` (line 289):** remove the `self._header.set_collapse_progress(0.0)` line. Nothing else in that branch changes.

**Happy path in `load_commit` (lines 307–318):** keep `self._msg_view.setFixedHeight(msg_h)` (line 305). Delete the block from line 307 through line 318 — that is: the `detail_h = self._detail.maximumHeight()` line, the `spacing = self._header.layout().spacing()` line, `self._header.set_expanded_height(detail_h + msg_h + spacing)`, `self._header.set_collapse_progress(0.0)`, the explanatory comment, and `self._diff_scroll.verticalScrollBar().setValue(0)`. The scroll-top reset is no longer load-bearing: nothing downstream depends on the scroll value, and `_clear_blocks` plus the subsequent re-render produce a natural top-of-content view for the new commit.

**`set_buses`, `load_commit` (post-point 318), `_render_all_files`, `_clear_blocks`, `eventFilter`, `_restyle_themed_panels`:** untouched.

## Test Changes (Detailed)

**`tests/presentation/widgets/test_collapsing_header.py`** — deleted wholesale.

**`tests/presentation/widgets/test_diff_widget.py`** — remove these tests:

- `test_on_diff_scrolled_sets_progress_from_scroll_value` (~line 131)
- `test_on_diff_scrolled_clamps_past_expanded_height` (~line 147)
- `test_load_commit_resets_collapse_progress` (~line 160)
- `test_load_commit_error_resets_collapse_progress` (~line 176)
- The scrollbar-signal emit test (~line 192) that asserts scrolling drives collapse progress
- `test_on_diff_scrolled_zero_keeps_progress_expanded` (~line 204)

All other tests in that file stay. No replacement tests are added — the behavior being removed has no successor, and the remaining tests plus a full `uv run pytest tests/ -v` green run cover the rest.

## README Change

Delete the bullet at `README.md:16`:

```
- **Collapsing commit header** — commit info + message smoothly shrink as you scroll the diff, maximizing space for hunks (re-expands on scroll-up)
```

No other README lines are affected. The unrelated "collapsible sidebar tree" bullet at line 32 stays.

## Verification

1. `uv run pytest tests/ -v` — all green. No collapse-named tests remain in the tree.
2. `uv run python main.py` — launch the app.
3. Pick a commit with a long diff; scroll through it; confirm the commit info + commit message stay fixed in place at full size.
4. Switch between commits; confirm the header content updates and stays fully visible each time.
5. Trigger the error path by selecting a stale oid (e.g. after a rebase); confirm the panel clears without error and no `_header` AttributeError surfaces.
6. Confirm the empty state (no commit selected) hides `_detail`, `_msg_view`, and the splitter.

## Risks

- **Stale references to `self._header`.** If any are missed they will surface as `AttributeError` on the first commit load. Mitigation: the file is small; every reference was enumerated above. A repo-wide grep for `_header` is part of the implementation plan.
- **Tests referencing the wrapper.** Same mitigation — enumerated above and covered by the pytest run.
- **Vertical-space regression.** Users with small windows who relied on the collapse to see more hunks may feel cramped. This is the expected trade-off of Option A; no mitigation is planned.
