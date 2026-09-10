# Collapsing Commit Header Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the commit info + message in `DiffWidget` as the user scrolls the diff hunks, in the style of an MD3 medium/large top app bar (parallax shrink, fully gone at max collapse). File list stays pinned.

**Architecture:** A new `CollapsingHeader` presentation widget wraps the existing `CommitDetailWidget` + commit-message `QPlainTextEdit`. It exposes a single narrow API — `set_collapse_progress(p: float)` — that interpolates its own `maximumHeight` from `expanded_height → 0`. `DiffWidget` connects the diff scroll area's `valueChanged` signal to a handler that maps scroll value → progress. All dynamic behavior lives in the widget's input/output; there are no timers, threads, or animations.

**Tech Stack:** Python 3.13, PySide6 (Qt), pytest + pytest-qt.

**Spec:** `docs/superpowers/specs/2026-04-17-collapsing-commit-header-design.md`

---

## File Structure

**New files:**
- `git_gui/presentation/widgets/collapsing_header.py` — the widget.
- `tests/presentation/widgets/test_collapsing_header.py` — unit tests for the widget in isolation.

**Modified files:**
- `git_gui/presentation/widgets/diff.py` — wrap `_detail` + `_msg_view` in a `CollapsingHeader`; wire scroll listener; reset on commit load.
- `tests/presentation/widgets/test_diff_widget.py` — add three wiring tests (handler maps scroll → progress; clamps past max; reset on reload).

**Not touched:** domain, application, infrastructure, `commit_detail.py`, `viewport_block_loader.py`, `working_tree.py`, `hunk_diff.py`, theme, QSS template.

---

## Task 1: `CollapsingHeader` widget (TDD)

Create the widget and its unit tests together. The widget is pure input-to-size mapping with no scroll listening of its own, so tests can exercise every code path directly.

**Files:**
- Create: `git_gui/presentation/widgets/collapsing_header.py`
- Create: `tests/presentation/widgets/test_collapsing_header.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/presentation/widgets/test_collapsing_header.py`:

```python
"""Unit tests for CollapsingHeader — the parallax-shrink container
around commit detail + commit message in DiffWidget."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QPlainTextEdit

from git_gui.presentation.widgets.collapsing_header import CollapsingHeader
from git_gui.presentation.widgets.commit_detail import CommitDetailWidget


@pytest.fixture
def header(qtbot):
    detail = CommitDetailWidget()
    msg = QPlainTextEdit()
    h = CollapsingHeader(detail, msg)
    qtbot.addWidget(h)
    return h, detail, msg


def test_expanded_progress_zero_sets_full_height(header):
    h, _, _ = header
    h.set_expanded_height(200)
    h.set_collapse_progress(0.0)
    assert h.maximumHeight() == 200


def test_fully_collapsed_progress_one_sets_zero_height(header):
    h, _, _ = header
    h.set_expanded_height(200)
    h.set_collapse_progress(1.0)
    assert h.maximumHeight() == 0


def test_half_progress_sets_half_height(header):
    h, _, _ = header
    h.set_expanded_height(200)
    h.set_collapse_progress(0.5)
    assert h.maximumHeight() == 100


def test_progress_below_zero_clamps(header):
    h, _, _ = header
    h.set_expanded_height(200)
    h.set_collapse_progress(-0.3)
    assert h.collapse_progress() == 0.0
    assert h.maximumHeight() == 200


def test_progress_above_one_clamps(header):
    h, _, _ = header
    h.set_expanded_height(200)
    h.set_collapse_progress(2.0)
    assert h.collapse_progress() == 1.0
    assert h.maximumHeight() == 0


def test_zero_expanded_height_gives_zero_max_regardless_of_progress(header):
    h, _, _ = header
    h.set_expanded_height(0)
    h.set_collapse_progress(0.0)
    assert h.maximumHeight() == 0
    h.set_collapse_progress(0.5)
    assert h.maximumHeight() == 0


def test_changing_expanded_height_reapplies_current_progress(header):
    h, _, _ = header
    h.set_expanded_height(200)
    h.set_collapse_progress(0.5)
    assert h.maximumHeight() == 100

    h.set_expanded_height(400)
    # progress is still 0.5 → max height should be 400 * 0.5 = 200
    assert h.maximumHeight() == 200


def test_negative_expanded_height_clamps_to_zero(header):
    h, _, _ = header
    h.set_expanded_height(-100)
    assert h.expanded_height() == 0
    assert h.maximumHeight() == 0


def test_children_are_reparented_into_header(header):
    h, detail, msg = header
    # Both children should now have the header as their parent.
    assert detail.parent() is h
    assert msg.parent() is h


def test_initial_state_has_zero_max_height(qtbot):
    """Before set_expanded_height is ever called, the header collapses to 0
    rather than showing its children at uncontrolled sizes."""
    detail = CommitDetailWidget()
    msg = QPlainTextEdit()
    h = CollapsingHeader(detail, msg)
    qtbot.addWidget(h)
    assert h.maximumHeight() == 0
    assert h.expanded_height() == 0
    assert h.collapse_progress() == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/presentation/widgets/test_collapsing_header.py -v`

Expected: all tests FAIL with `ModuleNotFoundError: No module named 'git_gui.presentation.widgets.collapsing_header'`.

- [ ] **Step 3: Implement the widget**

Create `git_gui/presentation/widgets/collapsing_header.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/presentation/widgets/test_collapsing_header.py -v`

Expected: all 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/widgets/collapsing_header.py tests/presentation/widgets/test_collapsing_header.py
git commit -m "feat(diff): add CollapsingHeader widget with progress API"
```

---

## Task 2: Integrate `CollapsingHeader` into `DiffWidget` (refactor only)

Replace the inline `_detail` + `_msg_view` wiring with a `CollapsingHeader`. No new behavior yet — `set_collapse_progress` is never called outside construction, so the header stays expanded once a commit is loaded. Existing `test_diff_widget.py` tests must still pass.

**Files:**
- Modify: `git_gui/presentation/widgets/diff.py`

- [ ] **Step 1: Add the import**

At `git_gui/presentation/widgets/diff.py`, top imports block (after line 14 next to `CommitDetailWidget`):

```python
from git_gui.presentation.widgets.collapsing_header import CollapsingHeader
```

- [ ] **Step 2: Wrap the two widgets in a `CollapsingHeader`**

In `DiffWidget.__init__`, right after the `self._msg_view.setFont(font)` line (currently `diff.py:125`), add:

```python
self._header = CollapsingHeader(self._detail, self._msg_view)
```

The `_detail` and `_msg_view` construction above this line is unchanged.

- [ ] **Step 3: Update the outer layout**

In `DiffWidget.__init__`, find the layout block (currently `diff.py:157-164`):

```python
layout = QVBoxLayout(self)
layout.setContentsMargins(12, 8, 12, 8)
layout.setSpacing(8)
layout.addWidget(self._state_banner, 0)
layout.addWidget(self._detail, 0)
layout.addWidget(self._msg_view, 0)
layout.addWidget(self._splitter, 1)
layout.addStretch()
```

Replace with:

```python
layout = QVBoxLayout(self)
layout.setContentsMargins(12, 8, 12, 8)
layout.setSpacing(8)
layout.addWidget(self._state_banner, 0)
layout.addWidget(self._header, 0)
layout.addWidget(self._splitter, 1)
layout.addStretch()
```

The `_detail` and `_msg_view` widgets are now reached through `self._header`'s layout. Do NOT also add them to the outer layout — `CollapsingHeader.__init__` already reparented them.

- [ ] **Step 4: Update `_set_empty_state`**

Find `_set_empty_state` (currently `diff.py:176-180`):

```python
def _set_empty_state(self, empty: bool) -> None:
    """Hide or show all sub-panels based on whether a commit is loaded."""
    self._detail.setVisible(not empty)
    self._msg_view.setVisible(not empty)
    self._splitter.setVisible(not empty)
```

Replace with:

```python
def _set_empty_state(self, empty: bool) -> None:
    """Hide or show all sub-panels based on whether a commit is loaded."""
    self._header.setVisible(not empty)
    self._splitter.setVisible(not empty)
```

`_detail` and `_msg_view` inherit visibility from `_header` because they are its children.

- [ ] **Step 5: Set the expanded height on commit load**

In `DiffWidget.load_commit`, find the block that sets the message's fixed height (currently `diff.py:287-292`):

```python
self._msg_view.setPlainText(msg)
line_count = msg.count("\n") + 1
line_h = self._msg_view.fontMetrics().lineSpacing()
doc_margin = self._msg_view.document().documentMargin() * 2
msg_h = int(line_count * line_h + doc_margin)
self._msg_view.setFixedHeight(msg_h)
```

Immediately **after** `self._msg_view.setFixedHeight(msg_h)`, add:

```python
# Inform the header of its natural (fully-expanded) height so the parallax
# shrink maps scroll position correctly. Both children have had
# setFixedHeight called, so .maximumHeight() is the authoritative value
# and is available synchronously.
detail_h = self._detail.maximumHeight()
spacing = self._header.layout().spacing()
self._header.set_expanded_height(detail_h + msg_h + spacing)
self._header.set_collapse_progress(0.0)
```

- [ ] **Step 6: Run existing `DiffWidget` tests**

Run: `uv run pytest tests/presentation/widgets/test_diff_widget.py -v`

Expected: all existing tests PASS (no new tests added yet). Tests asserting `_detail.isVisible()` / `_msg_view.isVisible()` still pass because Qt propagates visibility through parents; when `_header` is visible, its children are too.

- [ ] **Step 7: Run full test suite to confirm no regressions**

Run: `uv run pytest tests/ -v`

Expected: previously-passing tests still pass.

- [ ] **Step 8: Commit**

```bash
git add git_gui/presentation/widgets/diff.py
git commit -m "refactor(diff): wrap commit detail + message in CollapsingHeader"
```

---

## Task 3: Drive collapse from scroll + reset on commit load (TDD)

Add the scroll listener that converts scrollbar value → collapse progress, and force scroll position back to 0 on every commit load.

**Files:**
- Modify: `git_gui/presentation/widgets/diff.py`
- Modify: `tests/presentation/widgets/test_diff_widget.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/presentation/widgets/test_diff_widget.py` (end of file):

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/presentation/widgets/test_diff_widget.py -v -k "collapse or scroll"`

Expected: all 5 new tests FAIL (either `AttributeError: 'DiffWidget' object has no attribute '_on_diff_scrolled'` or the progress doesn't update because the signal isn't wired).

- [ ] **Step 3: Add the handler and wire the signal**

In `DiffWidget.__init__`, find the loader setup block (currently `diff.py:140`):

```python
self._loader = ViewportBlockLoader(self._diff_scroll, self._realize_block)
```

Immediately **after** that line, add:

```python
self._diff_scroll.verticalScrollBar().valueChanged.connect(
    self._on_diff_scrolled
)
```

Add the handler as a method of `DiffWidget`. Put it near `_on_theme_changed` (around `diff.py:224`):

```python
def _on_diff_scrolled(self, value: int) -> None:
    """Map diff scroll position to CollapsingHeader progress."""
    expanded = self._header.expanded_height()
    if expanded <= 0:
        self._header.set_collapse_progress(0.0)
        return
    self._header.set_collapse_progress(value / expanded)
```

- [ ] **Step 4: Reset scroll to 0 on commit load**

Inside `load_commit`, immediately **after** the `set_expanded_height` + `set_collapse_progress(0.0)` block you added in Task 2 Step 5, append:

```python
# Force scroll to the top — triggers valueChanged if value was non-zero,
# which also zeros collapse progress as a side-effect. The explicit
# set_collapse_progress(0.0) above handles the already-at-zero case.
self._diff_scroll.verticalScrollBar().setValue(0)
```

The full added block now reads:

```python
detail_h = self._detail.maximumHeight()
spacing = self._header.layout().spacing()
self._header.set_expanded_height(detail_h + msg_h + spacing)
self._header.set_collapse_progress(0.0)
self._diff_scroll.verticalScrollBar().setValue(0)
```

- [ ] **Step 5: Reset on error path**

Inside `load_commit`'s `except Exception` block (currently `diff.py:269-277`), find:

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

Add one line before `return`:

```python
except Exception as e:
    logger.warning("Failed to load commit %r: %s", oid, e)
    self._current_oid = None
    self._detail.clear()
    self._msg_view.clear()
    self._diff_model.reload([])
    self._clear_blocks()
    self._set_empty_state(True)
    self._header.set_collapse_progress(0.0)
    return
```

- [ ] **Step 6: Run the new tests to verify they pass**

Run: `uv run pytest tests/presentation/widgets/test_diff_widget.py -v -k "collapse or scroll"`

Expected: all 5 new tests PASS.

- [ ] **Step 7: Run the full `test_diff_widget.py` file**

Run: `uv run pytest tests/presentation/widgets/test_diff_widget.py -v`

Expected: all tests PASS (both the original 4 and the 5 new ones).

- [ ] **Step 8: Run the full test suite**

Run: `uv run pytest tests/ -v`

Expected: previously-passing tests still pass. No regressions.

- [ ] **Step 9: Manual smoke test**

Run: `uv run python main.py`

Open any repo with commits and several files changed. Click a commit in the graph. Confirm:
- Commit info + message are fully visible at the top of the diff panel.
- Scrolling down inside the diff hunks smoothly shrinks the commit info + message.
- At full scroll, the commit info + message are gone; file list is still visible above the hunks.
- Scrolling back up smoothly re-expands them.
- Clicking a different commit resets the header to fully expanded.
- The state banner (if you're mid-merge/rebase) stays pinned at the top and does not collapse.

If manual smoke fails on any of these, revisit the offending step — do NOT add code beyond what the plan specifies.

- [ ] **Step 10: Commit**

```bash
git add git_gui/presentation/widgets/diff.py tests/presentation/widgets/test_diff_widget.py
git commit -m "feat(diff): collapse commit header as diff hunks scroll"
```

---

## Done

After Task 3 commit, the feature is complete. The branch can be merged via the finishing-a-development-branch skill.
