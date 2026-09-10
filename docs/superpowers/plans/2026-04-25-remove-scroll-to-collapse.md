# Remove Scroll-to-Collapse Commit Header — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the scroll-driven parallax-shrink behavior on the commit-detail + commit-message header in `DiffWidget`. After this change the header is always fully visible above the file list and diff.

**Architecture:** Pure removal. Delete the `CollapsingHeader` wrapper widget and its test file; inline `_detail` and `_msg_view` directly into `DiffWidget`'s vertical layout where the wrapper used to sit; drop the scrollbar→handler wiring and every `set_collapse_progress` / `set_expanded_height` call. No new abstractions, no replacement UX.

**Tech Stack:** Python, PySide6, pygit2, pytest, pytest-qt, uv.

**Spec:** `docs/superpowers/specs/2026-04-25-remove-scroll-to-collapse-design.md`

---

## File Map

| Path | Action |
|------|--------|
| `git_gui/presentation/widgets/collapsing_header.py` | Delete |
| `tests/presentation/widgets/test_collapsing_header.py` | Delete |
| `git_gui/presentation/widgets/diff.py` | Modify (remove import, wrapper, scroll handler, layout swap, empty-state widgets, load_commit cleanup) |
| `tests/presentation/widgets/test_diff_widget.py` | Modify (remove section "5. Collapsing header wiring" — lines 128–214) |
| `README.md` | Modify (remove bullet at line 16) |

Untouched: domain, application, infrastructure, theme, QSS, splitter, file list view, viewport block loader, working-tree panel, state banner, the historical 2026-04-17 spec/plan docs.

---

## Task 1: Baseline — confirm tests pass before any changes

**Files:** none modified.

- [ ] **Step 1: Run the full test suite from a clean working tree**

Run: `uv run pytest tests/ -v`

Expected: all tests pass. Note the count for comparison after the removal. The collapse-related tests that will be removed in Task 2 should be in this baseline pass list:

```
tests/presentation/widgets/test_collapsing_header.py  (9 tests)
tests/presentation/widgets/test_diff_widget.py::test_on_diff_scrolled_sets_progress_from_scroll_value
tests/presentation/widgets/test_diff_widget.py::test_on_diff_scrolled_clamps_past_expanded_height
tests/presentation/widgets/test_diff_widget.py::test_load_commit_resets_collapse_progress
tests/presentation/widgets/test_diff_widget.py::test_load_commit_error_resets_collapse_progress
tests/presentation/widgets/test_diff_widget.py::test_scrollbar_valueChanged_drives_handler
tests/presentation/widgets/test_diff_widget.py::test_on_diff_scrolled_zero_keeps_progress_expanded
```

If anything fails on a clean tree, stop and surface the failure before proceeding — the rest of this plan assumes a green baseline.

---

## Task 2: Remove the scroll-to-collapse feature

**Files:**
- Delete: `git_gui/presentation/widgets/collapsing_header.py`
- Delete: `tests/presentation/widgets/test_collapsing_header.py`
- Modify: `git_gui/presentation/widgets/diff.py`
- Modify: `tests/presentation/widgets/test_diff_widget.py`

This task is one logical change — production removal plus its tests — and ends in one commit.

### 2.1 Remove the now-obsolete tests first

These tests reference `widget._header`, `widget._on_diff_scrolled`, and `widget._header.set_collapse_progress`. After Task 2.2 they would all error with `AttributeError`. Delete them up front so the test suite stays sane through every intermediate state.

- [ ] **Step 1: Delete `tests/presentation/widgets/test_collapsing_header.py`**

Run: `rm tests/presentation/widgets/test_collapsing_header.py`

Expected: file removed.

- [ ] **Step 2: Remove the entire "Collapsing header wiring" section from `tests/presentation/widgets/test_diff_widget.py`**

Open `tests/presentation/widgets/test_diff_widget.py`. Delete from line 128 (the comment `# ── 5. Collapsing header wiring ──────────────────────────────────────`) to the end of the file. After the deletion the file should end with the body of `test_clear_blocks_clears_loader` (the last assertion at the existing line 125, `assert widget._loader._diff_map == {}`).

Concretely, the block to remove is:

```python
# ── 5. Collapsing header wiring ──────────────────────────────────────


def test_on_diff_scrolled_sets_progress_from_scroll_value(diff_widget, qtbot):
    """Scrolling the diff area updates the header collapse progress."""
    widget, _ = diff_widget

    with patch("threading.Thread"):
        widget.load_commit("abc123")

    expanded = widget._header.expanded_height()
    assert expanded > 0  # sanity: mock commit has a message, so expanded > 0

    widget._on_diff_scrolled(expanded // 2)

    p = widget._header.collapse_progress()
    assert 0.45 <= p <= 0.55


def test_on_diff_scrolled_clamps_past_expanded_height(diff_widget, qtbot):
    """Scrolling past the expanded header height pins progress at 1.0."""
    widget, _ = diff_widget

    with patch("threading.Thread"):
        widget.load_commit("abc123")

    expanded = widget._header.expanded_height()
    widget._on_diff_scrolled(expanded * 3)

    assert widget._header.collapse_progress() == 1.0


def test_load_commit_resets_collapse_progress(diff_widget, qtbot):
    """A commit reload puts the header back to fully-expanded state."""
    widget, _ = diff_widget

    with patch("threading.Thread"):
        widget.load_commit("abc123")

    widget._header.set_collapse_progress(0.8)
    assert widget._header.collapse_progress() == 0.8

    with patch("threading.Thread"):
        widget.load_commit("abc123")

    assert widget._header.collapse_progress() == 0.0


def test_load_commit_error_resets_collapse_progress(diff_widget, qtbot):
    """A failed commit load also puts the header back to progress 0."""
    widget, queries = diff_widget

    with patch("threading.Thread"):
        widget.load_commit("abc123")
    widget._header.set_collapse_progress(0.7)

    queries.get_commit_detail.execute.side_effect = RuntimeError("gone")
    widget.load_commit("bad_oid")

    assert widget._header.collapse_progress() == 0.0


def test_scrollbar_valueChanged_drives_handler(diff_widget, qtbot):
    """The signal from the diff scroll bar is connected to the handler —
    emitting it updates collapse progress without a direct call."""
    widget, _ = diff_widget

    with patch("threading.Thread"):
        widget.load_commit("abc123")

    expanded = widget._header.expanded_height()
    widget._diff_scroll.verticalScrollBar().valueChanged.emit(expanded)

    assert widget._header.collapse_progress() == 1.0


def test_on_diff_scrolled_zero_keeps_progress_expanded(diff_widget, qtbot):
    """Scrolling back to the top re-expands the header (progress 0.0)."""
    widget, _ = diff_widget

    with patch("threading.Thread"):
        widget.load_commit("abc123")

    widget._header.set_collapse_progress(0.6)
    widget._on_diff_scrolled(0)

    assert widget._header.collapse_progress() == 0.0
```

After deletion, the last lines of `test_diff_widget.py` should be the closing of `test_clear_blocks_clears_loader`:

```python
    widget._clear_blocks()

    assert widget._loader._block_refs == []
    assert widget._loader._loaded_paths == set()
    assert widget._loader._diff_map == {}
```

- [ ] **Step 3: Run the test suite — expect failures**

Run: `uv run pytest tests/presentation/widgets/test_diff_widget.py -v`

Expected: PASS. The deleted tests no longer run; the four remaining tests in this file (`test_load_commit_shows_panels`, `test_load_commit_error_hides_panels`, `test_set_buses_none_enters_empty_state`, `test_clear_blocks_clears_loader`) still pass because production code is unchanged so far.

If the four remaining tests fail, stop — they should not be impacted by deleting other tests in the same file.

### 2.2 Apply the production-code changes in `diff.py`

All edits are in `git_gui/presentation/widgets/diff.py`. Line numbers below refer to the file as it stands at the start of the change (matching the spec).

- [ ] **Step 4: Remove the `CollapsingHeader` import**

Find line 15:

```python
from git_gui.presentation.widgets.collapsing_header import CollapsingHeader
```

Delete the entire line. The `from git_gui.presentation.widgets.commit_detail import CommitDetailWidget` line above and the `from git_gui.presentation.widgets.file_list_view import FileListView as _FileListView` line below stay.

- [ ] **Step 5: Remove the wrapper construction**

Find line 128:

```python
        self._header = CollapsingHeader(self._detail, self._msg_view)
```

Delete the entire line. The `_detail` construction at lines 113–114 and the `_msg_view` construction at lines 117–126 stay exactly as written. Both attributes remain first-class members of `DiffWidget`.

- [ ] **Step 6: Remove the scrollbar → handler connection**

Find lines 144–146:

```python
        self._diff_scroll.verticalScrollBar().valueChanged.connect(
            self._on_diff_scrolled
        )
```

Delete all three lines. The `self._loader = ViewportBlockLoader(self._diff_scroll, self._realize_block)` line above stays.

- [ ] **Step 7: Replace the wrapper in the outer layout with the two children**

Find line 167 inside the layout-construction block:

```python
        layout.addWidget(self._header, 0)
```

Replace with:

```python
        layout.addWidget(self._detail, 0)
        layout.addWidget(self._msg_view, 0)
```

The surrounding `layout.addWidget(self._state_banner, 0)` (above) and `layout.addWidget(self._splitter, 1)` (below) stay unchanged. After this edit the layout adds, in order: state banner, commit detail, commit message, splitter, stretch.

- [ ] **Step 8: Update `_set_empty_state` to toggle the children directly**

Find `_set_empty_state` at lines 181–184:

```python
    def _set_empty_state(self, empty: bool) -> None:
        """Hide or show all sub-panels based on whether a commit is loaded."""
        self._header.setVisible(not empty)
        self._splitter.setVisible(not empty)
```

Replace with:

```python
    def _set_empty_state(self, empty: bool) -> None:
        """Hide or show all sub-panels based on whether a commit is loaded."""
        self._detail.setVisible(not empty)
        self._msg_view.setVisible(not empty)
        self._splitter.setVisible(not empty)
```

- [ ] **Step 9: Delete the `_on_diff_scrolled` method**

Find the method at lines 233–239:

```python
    def _on_diff_scrolled(self, value: int) -> None:
        """Map diff scroll position to CollapsingHeader progress."""
        expanded = self._header.expanded_height()
        if expanded <= 0:
            self._header.set_collapse_progress(0.0)
            return
        self._header.set_collapse_progress(value / expanded)
```

Delete the entire method, including the blank line immediately after it. The `_on_theme_changed` method above and the `_restyle_themed_panels` method below stay.

- [ ] **Step 10: Remove the collapse-reset call in the `load_commit` error path**

Find line 289 inside the `except Exception as e:` branch of `load_commit`:

```python
            self._header.set_collapse_progress(0.0)
```

Delete this single line. The `self._set_empty_state(True)` line above and the `return` line below stay. The error branch becomes:

```python
        except Exception as e:
            logger.warning("Failed to load commit %r: %s", oid, e)
            self._current_oid = None
            self._detail.clear()
            self._msg_view.clear()
            self._diff_model.reload([])
            self._clear_blocks()
            self._set_empty_state(True)
            return
```

- [ ] **Step 11: Remove the collapse-driving block in the `load_commit` happy path**

Find lines 307–318 in `load_commit`:

```python
        # Both children have had setFixedHeight called upstream, so
        # .maximumHeight() is the authoritative natural height synchronously —
        # no sizeHint / event-loop round-trip needed.
        detail_h = self._detail.maximumHeight()
        spacing = self._header.layout().spacing()
        self._header.set_expanded_height(detail_h + msg_h + spacing)
        self._header.set_collapse_progress(0.0)

        # Force scroll to the top — triggers valueChanged if value was non-zero,
        # which also zeros collapse progress as a side-effect. The explicit
        # set_collapse_progress(0.0) above handles the already-at-zero case.
        self._diff_scroll.verticalScrollBar().setValue(0)
```

Delete this entire block. The line immediately above (`self._msg_view.setFixedHeight(msg_h)` at line 305) stays — it is still load-bearing for sizing the message widget to its content. The line immediately below (`# Files — no auto-selection; show all files' hunks as bordered blocks` at line 320, followed by `files = self._queries.get_commit_files.execute(oid)`) stays.

After this edit, the tail of `load_commit` reads:

```python
        msg = commit.message
        if not msg.endswith("\n"):
            msg += "\n"
        self._msg_view.setPlainText(msg)
        line_count = msg.count("\n") + 1
        line_h = self._msg_view.fontMetrics().lineSpacing()
        doc_margin = self._msg_view.document().documentMargin() * 2
        msg_h = int(line_count * line_h + doc_margin)
        self._msg_view.setFixedHeight(msg_h)

        # Files — no auto-selection; show all files' hunks as bordered blocks
        files = self._queries.get_commit_files.execute(oid)
        self._diff_model.reload(files)
        self._render_all_files(oid)
```

### 2.3 Delete the wrapper widget

Now nothing imports `CollapsingHeader`.

- [ ] **Step 12: Verify `CollapsingHeader` has no remaining references**

Run: `rtk grep -n "CollapsingHeader\|collapsing_header\|_header\b\|_on_diff_scrolled\|set_collapse_progress\|set_expanded_height\|collapse_progress\|expanded_height" git_gui/ tests/`

Expected: no matches in `git_gui/` or `tests/`. (The only files that referenced these symbols were `git_gui/presentation/widgets/diff.py`, `git_gui/presentation/widgets/collapsing_header.py`, `tests/presentation/widgets/test_diff_widget.py`, and `tests/presentation/widgets/test_collapsing_header.py`. After steps 1–11 only the two collapsing-header files remain — and those are about to go.)

If a match shows up in any other file, stop and surface it — the spec did not anticipate it and it must be triaged before proceeding.

- [ ] **Step 13: Delete `git_gui/presentation/widgets/collapsing_header.py`**

Run: `rm git_gui/presentation/widgets/collapsing_header.py`

Expected: file removed.

- [ ] **Step 14: Re-grep to confirm zero references**

Run: `rtk grep -n "CollapsingHeader\|collapsing_header" .`

Expected: matches only in `docs/superpowers/specs/2026-04-17-collapsing-commit-header-design.md` and `docs/superpowers/plans/2026-04-17-collapsing-commit-header.md` (the historical docs we are intentionally keeping). No matches in `git_gui/`, `tests/`, or `README.md`.

### 2.4 Verify

- [ ] **Step 15: Run the full test suite**

Run: `uv run pytest tests/ -v`

Expected: all tests pass. The pre-removal count minus the deleted tests should match. No errors, no warnings about missing fixtures/imports.

- [ ] **Step 16: Sanity-import `DiffWidget`**

Run: `uv run python -c "from git_gui.presentation.widgets.diff import DiffWidget; print('ok')"`

Expected: prints `ok`. Confirms there are no dangling imports of the deleted module.

### 2.5 Commit

- [ ] **Step 17: Stage and commit**

```bash
rtk git add -A
rtk git status
```

Expected: status shows the `diff.py` modification, the `test_diff_widget.py` modification, and deletions of `collapsing_header.py` and `test_collapsing_header.py`. No other files staged.

Then:

```bash
rtk git commit -m "$(cat <<'EOF'
refactor(diff): remove scroll-to-collapse commit header

The 2026-04-17 collapsing commit header (CollapsingHeader wrapper +
parallax-shrink on diff scroll) is removed. Commit detail and commit
message are now always fully visible above the file list and diff.

- Delete CollapsingHeader widget and its unit tests
- Inline _detail and _msg_view into DiffWidget's vertical layout
- Drop scrollbar valueChanged wiring and _on_diff_scrolled handler
- Drop set_expanded_height / set_collapse_progress calls in load_commit
- Update _set_empty_state to toggle the two children directly

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds; pre-commit hook (if any) passes.

---

## Task 3: Update README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Remove the collapse bullet**

Open `README.md`. Find line 16:

```
- **Collapsing commit header** — commit info + message smoothly shrink as you scroll the diff, maximizing space for hunks (re-expands on scroll-up)
```

Delete the entire line. The bullet on line 15 (`- Click any commit to view its file list and unified diff`) and the bullet on line 17 (`- **Auto-refresh** — …`) stay. The unrelated "collapsible sidebar tree" bullet at line 32 stays.

- [ ] **Step 2: Verify the diff is exactly one line removed**

Run: `rtk git diff README.md`

Expected: a single removed line containing "Collapsing commit header". Nothing else changed.

- [ ] **Step 3: Commit**

```bash
rtk git add README.md
rtk git commit -m "$(cat <<'EOF'
docs(readme): drop scroll-to-collapse bullet

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds.

---

## Task 4: Manual verification

**Files:** none modified. No commit.

This is a smoke test of the running application. The repository under test can be GitStack itself or any other repo with a non-trivial commit history.

- [ ] **Step 1: Launch the app**

Run: `uv run python main.py`

Expected: the app opens without errors.

- [ ] **Step 2: Pick a commit with a long diff**

Open any repository with a commit that has many files / many hunks (a refactor commit is a good candidate). Click the commit in the graph view.

Expected: the right-hand panel shows the commit-detail row, then the commit message, then the file list, then the diff. All four are fully visible.

- [ ] **Step 3: Scroll through the diff**

Use the wheel, scrollbar drag, and PageDown to scroll through the diff hunks.

Expected: the commit-detail row and commit-message block stay in place at full size. They do not shrink, fade, or move as the diff scrolls. The file list and the splitter handle stay unaffected. (If anything in the header area changes visually as you scroll, the removal is incomplete — surface it.)

- [ ] **Step 4: Switch between commits**

Click a different commit, then back, then to a third commit.

Expected: the header content updates to match each commit; the header is always at full size on every load.

- [ ] **Step 5: Trigger the empty state**

Either start the app fresh, or reload the repo such that no commit is selected.

Expected: the commit-detail row, commit message, and splitter are all hidden (empty state is intact).

- [ ] **Step 6: Trigger the error path** (optional but recommended)

Make a selection that triggers `get_commit_detail` to raise. The simplest trigger: rebase or reset the working repo to drop a commit, then click the now-missing commit in the cached graph.

Expected: the panel clears without an `AttributeError` (the previous code referenced `self._header`; the new code does not). A warning is logged via `logger.warning("Failed to load commit %r: %s", oid, e)`.

If all six steps pass, the removal is verified end-to-end. If any UI-only step fails, surface it explicitly — the test suite cannot catch UI regressions.

---

## Self-Review Notes

- **Spec coverage:** every modify/delete entry in the spec's "Files Changed" table maps to a step in Task 2 or Task 3. The `_set_empty_state` rewrite, the `_on_diff_scrolled` deletion, both `load_commit` cleanups, the wrapper deletion, and the test deletions are each their own step.
- **Type/symbol consistency:** the names used here (`_detail`, `_msg_view`, `_splitter`, `_state_banner`, `_diff_scroll`, `_loader`, `_set_empty_state`, `load_commit`) all match the existing `DiffWidget` source verified during brainstorming. The collapse-related symbols (`_header`, `_on_diff_scrolled`, `set_collapse_progress`, `set_expanded_height`, `collapse_progress`, `expanded_height`, `CollapsingHeader`) appear only in deletion steps and the final grep verification.
- **No placeholders:** every code block is the literal text to remove or insert; every command line is runnable; every expected-output line is concrete.
