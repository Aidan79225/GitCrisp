# Collapsible Commit Message + Diff Block Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-component expand/collapse toggles so the user can hide a file's hunks (leaving only the file header row) and shrink the commit message to its subject line.

**Architecture:** Three small commits. (1) A new reusable `_CollapseToggle` chevron widget. (2) `make_file_block` in `diff_block.py` adds the toggle to its header row and wires it to hide non-header children. (3) `DiffWidget` wraps `_msg_view` in a panel with a slim header strip carrying the same toggle, which switches `_msg_view`'s fixed height between full and single-line.

**Tech Stack:** PySide6 (`QToolButton`, `QHBoxLayout`, `QVBoxLayout`, `QWidget`). Tests use `pytest-qt` (`qtbot`).

**Spec:** `docs/superpowers/specs/2026-05-08-collapsible-commit-and-hunks-design.md`

---

## File Structure

- **Create:** `git_gui/presentation/widgets/_collapse_toggle.py` — the reusable chevron button.
- **Create:** `tests/presentation/widgets/test_collapse_toggle.py` — toggle behavior tests.
- **Modify:** `git_gui/presentation/widgets/diff_block.py` — `make_file_block` adds a toggle to the header row.
- **Modify:** `tests/presentation/widgets/test_diff_block.py` — add a test for the toggle's hide/show behavior.
- **Modify:** `git_gui/presentation/widgets/diff.py` — wrap `_msg_view` in `_msg_panel`; add toggle wiring; route `_set_empty_state` and the visibility toggle through the new panel.
- **Modify:** `tests/presentation/widgets/test_diff_widget.py` — add a test for the message collapse/expand height switch.

---

## Task 1: Reusable `_CollapseToggle` widget

TDD: write the test first, see it fail, implement, see it pass.

**Files:**
- Create: `tests/presentation/widgets/test_collapse_toggle.py`
- Create: `git_gui/presentation/widgets/_collapse_toggle.py`

- [ ] **Step 1: Write the failing test**

Create `tests/presentation/widgets/test_collapse_toggle.py`:

```python
"""Tests for _CollapseToggle (reusable chevron toggle button)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from git_gui.presentation.widgets._collapse_toggle import _CollapseToggle


def _app():
    return QApplication.instance() or QApplication([])


def test_initial_state_expanded(qtbot):
    _app()
    toggle = _CollapseToggle(expanded=True)
    qtbot.addWidget(toggle)
    assert toggle.is_expanded() is True
    assert toggle.arrowType() == Qt.DownArrow


def test_initial_state_collapsed(qtbot):
    _app()
    toggle = _CollapseToggle(expanded=False)
    qtbot.addWidget(toggle)
    assert toggle.is_expanded() is False
    assert toggle.arrowType() == Qt.RightArrow


def test_click_toggles_state_and_arrow(qtbot):
    _app()
    toggle = _CollapseToggle(expanded=True)
    qtbot.addWidget(toggle)

    received: list[bool] = []
    toggle.state_changed.connect(lambda s: received.append(s))

    toggle.click()
    assert toggle.is_expanded() is False
    assert toggle.arrowType() == Qt.RightArrow
    assert received == [False]

    toggle.click()
    assert toggle.is_expanded() is True
    assert toggle.arrowType() == Qt.DownArrow
    assert received == [False, True]
```

- [ ] **Step 2: Run the test and confirm FAIL**

Run: `rtk uv run pytest tests/presentation/widgets/test_collapse_toggle.py -v`

Expected: 3 FAIL — module `_collapse_toggle` does not exist.

- [ ] **Step 3: Implement `_CollapseToggle`**

Create `git_gui/presentation/widgets/_collapse_toggle.py`:

```python
"""Reusable chevron toggle button used by collapsible diff sections."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QToolButton


class _CollapseToggle(QToolButton):
    """Down/right chevron toggle.

    Emits state_changed(True) when expanded, False when collapsed.
    Compact (16x16), auto-raise so it sits flush in a header row.
    """

    state_changed = Signal(bool)

    def __init__(self, expanded: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(expanded)
        self.setAutoRaise(True)
        self.setFixedSize(QSize(16, 16))
        self.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.setCursor(Qt.PointingHandCursor)
        self.toggled.connect(self._on_toggle)

    def _on_toggle(self, checked: bool) -> None:
        self.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        self.state_changed.emit(checked)

    def is_expanded(self) -> bool:
        return self.isChecked()
```

- [ ] **Step 4: Run the test and confirm PASS**

Run: `rtk uv run pytest tests/presentation/widgets/test_collapse_toggle.py -v`

Expected: 3 PASSED.

- [ ] **Step 5: Run the full suite as a sanity check**

Run: `rtk uv run pytest tests/ -q`

Expected: all PASSED. The new file isn't used anywhere yet, so the only effect is +3 tests.

- [ ] **Step 6: Commit**

```bash
rtk git add git_gui/presentation/widgets/_collapse_toggle.py tests/presentation/widgets/test_collapse_toggle.py
rtk git commit -m "$(cat <<'EOF'
feat(widgets): add reusable _CollapseToggle chevron button

Tiny QToolButton that flips between Qt.DownArrow (expanded) and
Qt.RightArrow (collapsed) on click. Emits state_changed(bool).
Auto-raise + fixed 16x16 so it sits flush in a header row.
Used by the upcoming diff-block and commit-message collapse work.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Per-file diff block toggle

TDD again. The function to modify is `make_file_block` in `git_gui/presentation/widgets/diff_block.py:106`.

**Files:**
- Modify: `tests/presentation/widgets/test_diff_block.py`
- Modify: `git_gui/presentation/widgets/diff_block.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/presentation/widgets/test_diff_block.py`:

```python
def test_make_file_block_collapse_hides_non_header_widgets(qtbot):
    """Toggling a file block to collapsed hides every widget inside `inner`
    except the header row at index 0."""
    from PySide6.QtWidgets import QLabel
    from git_gui.presentation.widgets.diff_block import make_file_block

    frame, inner = make_file_block("path/to/file.py")
    qtbot.addWidget(frame)
    # Add two pretend hunk widgets so we can verify they hide.
    hunk1 = QLabel("hunk 1")
    hunk2 = QLabel("hunk 2")
    inner.addWidget(hunk1)
    inner.addWidget(hunk2)

    frame.show()
    qtbot.wait(20)

    # Locate the toggle and verify all three children are visible to start.
    from git_gui.presentation.widgets._collapse_toggle import _CollapseToggle
    toggle = frame.findChild(_CollapseToggle)
    assert toggle is not None
    assert toggle.is_expanded() is True
    assert hunk1.isVisible()
    assert hunk2.isVisible()

    # Collapse — both hunks hide, header stays.
    toggle.click()
    assert toggle.is_expanded() is False
    assert not hunk1.isVisible()
    assert not hunk2.isVisible()
    # Header row (index 0 in inner) is still visible.
    header_widget = inner.itemAt(0).widget()
    assert header_widget is not None
    assert header_widget.isVisible()

    # Expand again — hunks come back.
    toggle.click()
    assert hunk1.isVisible()
    assert hunk2.isVisible()
```

- [ ] **Step 2: Run the test and confirm FAIL**

Run: `rtk uv run pytest tests/presentation/widgets/test_diff_block.py::test_make_file_block_collapse_hides_non_header_widgets -v`

Expected: FAIL — `frame.findChild(_CollapseToggle)` returns `None` because the toggle isn't there yet.

- [ ] **Step 3: Add toggle to `make_file_block`**

Open `git_gui/presentation/widgets/diff_block.py`. At the top, add the import:

```python
from git_gui.presentation.widgets._collapse_toggle import _CollapseToggle
```

In `make_file_block`, find the existing header-row construction (around line 127-140):

```python
    header_row = QWidget()
    header_row_layout = QHBoxLayout(header_row)
    header_row_layout.setContentsMargins(0, HEADER_ROW_VPAD, 0, HEADER_ROW_VPAD)
    header_row_layout.setSpacing(4)
    label_text = f"\U0001f4c4 {path}"
    if on_header_clicked is not None:
        header_label = _ClickableLabel(label_text, on_header_clicked)
    else:
        header_label = QLabel(label_text)
    header_label.setStyleSheet(_header_style())
    header_row_layout.addWidget(header_label)
    header_row_layout.addStretch()
    header_row.setFixedHeight(HEADER_ROW_HEIGHT + HEADER_ROW_VPAD * 2)
    inner.addWidget(header_row)
```

Insert the toggle BEFORE `header_label`. Wire its `state_changed` to a closure that hides every widget in `inner` after index 0:

```python
    header_row = QWidget()
    header_row_layout = QHBoxLayout(header_row)
    header_row_layout.setContentsMargins(0, HEADER_ROW_VPAD, 0, HEADER_ROW_VPAD)
    header_row_layout.setSpacing(4)
    toggle = _CollapseToggle(expanded=True)
    header_row_layout.addWidget(toggle)
    label_text = f"\U0001f4c4 {path}"
    if on_header_clicked is not None:
        header_label = _ClickableLabel(label_text, on_header_clicked)
    else:
        header_label = QLabel(label_text)
    header_label.setStyleSheet(_header_style())
    header_row_layout.addWidget(header_label)
    header_row_layout.addStretch()
    header_row.setFixedHeight(HEADER_ROW_HEIGHT + HEADER_ROW_VPAD * 2)
    inner.addWidget(header_row)

    def _set_expanded(expanded: bool) -> None:
        for i in range(1, inner.count()):
            item = inner.itemAt(i)
            w = item.widget() if item else None
            if w is not None:
                w.setVisible(expanded)

    toggle.state_changed.connect(_set_expanded)
```

The closure captures `inner` by reference; it's safe because `inner` lives as long as `frame` does.

- [ ] **Step 4: Run the test and confirm PASS**

Run: `rtk uv run pytest tests/presentation/widgets/test_diff_block.py::test_make_file_block_collapse_hides_non_header_widgets -v`

Expected: PASSED.

- [ ] **Step 5: Run the full diff_block test file**

Run: `rtk uv run pytest tests/presentation/widgets/test_diff_block.py tests/presentation/widgets/test_diff_block_syntax.py -v`

Expected: all PASSED.

- [ ] **Step 6: Run the full suite**

Run: `rtk uv run pytest tests/ -q`

Expected: all PASSED.

- [ ] **Step 7: Commit**

```bash
rtk git add git_gui/presentation/widgets/diff_block.py tests/presentation/widgets/test_diff_block.py
rtk git commit -m "$(cat <<'EOF'
feat(diff_block): add collapse toggle to file diff-block header

make_file_block now places a _CollapseToggle at the start of its
header row. When the user clicks it to collapse, every widget in
the frame's `inner` layout after index 0 (the header row itself) is
hidden — so only the "📄 path" line stays visible. Clicking again
restores them. Default state is expanded; no persistence between
files or commits.

Hunk widgets added to `inner` later by the realize/skeleton flow
are subject to the same visibility toggle — if the file is
collapsed when its skeleton realizes, the new hunk widgets land
hidden until the user expands.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Commit message panel toggle

TDD. We're adding a wrapping panel around `_msg_view` and a height-switching toggle. The test asserts the toggle exists and switches `_msg_view.height()` between roughly-one-line and the full message height.

**Files:**
- Modify: `tests/presentation/widgets/test_diff_widget.py`
- Modify: `git_gui/presentation/widgets/diff.py`

- [ ] **Step 1: Read the existing test fixture for context**

Read the top of `tests/presentation/widgets/test_diff_widget.py` (the first ~60 lines) to understand the `diff_widget` fixture and how `load_commit` is called. The fixture should already provide a working `DiffWidget` with mock buses — you'll reuse it.

- [ ] **Step 2: Write the failing test**

Append to `tests/presentation/widgets/test_diff_widget.py`:

```python
def test_message_collapse_shrinks_msg_view_to_subject_line(diff_widget, qtbot):
    """Toggling the commit message panel to collapsed shrinks _msg_view's
    fixed height down to one line of text plus the document margin.
    Expanding restores the full height that fits the multi-line body."""
    w = diff_widget

    # Need a multi-line message so collapse vs expand differ visibly.
    from datetime import datetime
    from git_gui.domain.entities import Commit
    multi_line_msg = "Subject line\n\nBody paragraph one.\nBody paragraph two."
    commit = Commit(
        oid="a" * 40,
        message=multi_line_msg,
        author="Alice <a@example.com>",
        timestamp=datetime(2026, 5, 8, 12, 0),
        parents=[],
    )
    # Drive load_commit through the underlying queries mock.
    w._queries.get_commit_detail.execute.return_value = commit
    w._queries.get_branches.execute.return_value = []
    w._queries.get_commit_files.execute.return_value = []
    w._queries.get_commit_diff_map.execute.return_value = {}
    w.load_commit(commit.oid)
    qtbot.wait(20)

    full_h = w._msg_view.height()
    assert full_h > 0

    # Collapse — height shrinks.
    w._msg_toggle.click()
    qtbot.wait(20)
    collapsed_h = w._msg_view.height()
    assert collapsed_h < full_h
    # One-line height is roughly fontMetrics().lineSpacing() + margins,
    # which is significantly smaller than four paragraphs.
    line_h = w._msg_view.fontMetrics().lineSpacing()
    assert collapsed_h < line_h * 2 + 40  # generous upper bound

    # Expand — height returns to full.
    w._msg_toggle.click()
    qtbot.wait(20)
    assert w._msg_view.height() == full_h
```

- [ ] **Step 3: Run the test and confirm FAIL**

Run: `rtk uv run pytest tests/presentation/widgets/test_diff_widget.py::test_message_collapse_shrinks_msg_view_to_subject_line -v`

Expected: FAIL — `_msg_toggle` doesn't exist yet (`AttributeError`).

- [ ] **Step 4: Add the import for `_CollapseToggle` in `diff.py`**

Open `git_gui/presentation/widgets/diff.py`. Near the top, alongside the other widget imports:

```python
from git_gui.presentation.widgets._collapse_toggle import _CollapseToggle
```

- [ ] **Step 5: Wrap `_msg_view` in `_msg_panel` with a header strip**

Find the existing `_msg_view` construction block (around line 188). Currently:

```python
        self._msg_view = QPlainTextEdit()
        self._msg_view.setReadOnly(True)
        self._msg_view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self._msg_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._msg_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._msg_view.viewport().installEventFilter(self)
        self._msg_view.document().setDocumentMargin(12)
        font = self._msg_view.font()
        # ...font config...
        self._msg_view.setFont(font)
```

Immediately after this block (and before the line `scroll_content_layout.addWidget(self._msg_view)`), add the wrapping panel:

```python
        # Wrap the message view in a panel with a slim collapsible header.
        self._msg_panel = QWidget()
        msg_panel_layout = QVBoxLayout(self._msg_panel)
        msg_panel_layout.setContentsMargins(0, 0, 0, 0)
        msg_panel_layout.setSpacing(2)

        msg_header_row = QHBoxLayout()
        msg_header_row.setContentsMargins(0, 0, 0, 0)
        msg_header_row.setSpacing(4)
        self._msg_toggle = _CollapseToggle(expanded=True)
        msg_header_row.addWidget(self._msg_toggle)
        self._msg_header_label = QLabel("Message")
        msg_header_row.addWidget(self._msg_header_label)
        msg_header_row.addStretch()

        msg_panel_layout.addLayout(msg_header_row)
        msg_panel_layout.addWidget(self._msg_view)

        # Cached heights filled in by load_commit; expanded by default.
        self._msg_full_h: int = 0
        self._msg_collapsed_h: int = 0
        self._msg_toggle.state_changed.connect(self._on_msg_toggle)
```

Find the existing `scroll_content_layout.addWidget(self._msg_view)` line (around line 234) and replace it with `scroll_content_layout.addWidget(self._msg_panel)`.

- [ ] **Step 6: Add the toggle handler**

Add the new method anywhere in the `DiffWidget` class — placing it next to `_set_empty_state` is natural:

```python
    def _on_msg_toggle(self, expanded: bool) -> None:
        if self._msg_full_h <= 0 or self._msg_collapsed_h <= 0:
            return
        self._msg_view.setFixedHeight(
            self._msg_full_h if expanded else self._msg_collapsed_h
        )
```

- [ ] **Step 7: Update `_set_empty_state` to toggle `_msg_panel` instead of `_msg_view`**

Find:

```python
        self._msg_view.setVisible(not empty)
```

(There are two such call sites — `_set_empty_state` around line 271 and another in the empty-on-error path around line 372.) Replace each with:

```python
        self._msg_panel.setVisible(not empty)
```

- [ ] **Step 8: Update `load_commit` to remember both heights**

Find the existing height calculation in `load_commit` (around line 387-392):

```python
        self._msg_view.setPlainText(msg)
        line_count = msg.count("\n") + 1
        line_h = self._msg_view.fontMetrics().lineSpacing()
        doc_margin = self._msg_view.document().documentMargin() * 2
        msg_h = int(line_count * line_h + doc_margin)
        self._msg_view.setFixedHeight(msg_h)
```

Replace with:

```python
        self._msg_view.setPlainText(msg)
        line_count = msg.count("\n") + 1
        line_h = self._msg_view.fontMetrics().lineSpacing()
        doc_margin = self._msg_view.document().documentMargin() * 2
        self._msg_full_h = int(line_count * line_h + doc_margin)
        self._msg_collapsed_h = int(line_h + doc_margin)
        self._msg_view.setFixedHeight(
            self._msg_full_h if self._msg_toggle.is_expanded() else self._msg_collapsed_h
        )
```

The toggle's state is preserved across loads — if the user collapsed the message and then switches commits, the new commit's message also opens collapsed. Acceptable per spec.

- [ ] **Step 9: Update the empty-on-error path to clear the cached heights**

Find the error-path block in `load_commit` that calls `self._msg_view.clear()` (around line 372). Right after `self._msg_view.clear()`, also reset the cached heights so a subsequent collapse toggle is a no-op:

```python
            self._msg_view.clear()
            self._msg_full_h = 0
            self._msg_collapsed_h = 0
```

(There are two `clear()` call sites for `_msg_view`. Apply the same reset right after each.)

- [ ] **Step 10: Run the test and confirm PASS**

Run: `rtk uv run pytest tests/presentation/widgets/test_diff_widget.py::test_message_collapse_shrinks_msg_view_to_subject_line -v`

Expected: PASSED.

- [ ] **Step 11: Run the full diff_widget test file**

Run: `rtk uv run pytest tests/presentation/widgets/test_diff_widget.py -v`

Expected: all PASSED. The other tests don't reference `_msg_panel` or `_msg_toggle`, so they should be unaffected.

- [ ] **Step 12: Run the full suite**

Run: `rtk uv run pytest tests/ -q`

Expected: all PASSED.

- [ ] **Step 13: Commit**

```bash
rtk git add git_gui/presentation/widgets/diff.py tests/presentation/widgets/test_diff_widget.py
rtk git commit -m "$(cat <<'EOF'
feat(diff): collapsible commit message panel

Wrap _msg_view in a new _msg_panel that adds a slim header strip
with a "Message" label and a _CollapseToggle. Toggling collapsed
shrinks _msg_view to a single-line fixed height (subject line
only); toggling expanded restores the full height computed in
load_commit. The text content of the QPlainTextEdit is unchanged —
only the visible height shrinks, so the body is still in the
document but clipped from view.

_set_empty_state now hides the whole _msg_panel (not just
_msg_view), so the empty state cleanly hides both the message and
its header. The toggle's state is preserved across commit switches.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Manual verification

**Files:** none modified.

- [ ] **Step 1: Launch the app**

Run: `rtk uv run python main.py`

- [ ] **Step 2: Verify the file diff-block toggle**

Open a commit that touches multiple files. Each file's header row now shows a `▼` chevron at the left, before the `📄 path` label.

- Click the chevron on one file → its hunks hide; only the header row remains; chevron becomes `▶`.
- Click again → hunks return; chevron flips back to `▼`.
- Repeat on a different file → only that file collapses; others stay expanded.

- [ ] **Step 3: Verify the message toggle**

Open a commit with a multi-paragraph message. Above the message panel there is now a small header row: a `▼` chevron + the word "Message".

- Click the chevron → the message panel shrinks to show only the subject line; chevron becomes `▶`.
- Click again → full message returns; chevron is `▼`.

- [ ] **Step 4: Switch commits while collapsed**

Collapse the message. Click a different commit. Confirm the message stays collapsed (subject only) for the new commit. Expand → full new message shows.

Then collapse one file's hunks. Click a different commit. The new commit's files all open expanded by default — per-file collapse state does NOT carry across commits (each commit re-renders its file blocks). Expected.

- [ ] **Step 5: No commit needed**

Manual verification doesn't produce changes.

---

## Self-Review

**Spec coverage:**
- `_CollapseToggle` reusable widget → Task 1. ✅
- Per-file toggle hides non-header inner widgets → Task 2 Step 3. ✅
- Per-file toggle: default expanded → `_CollapseToggle(expanded=True)` in `make_file_block`. ✅
- Commit message panel wraps `_msg_view` with header strip → Task 3 Step 5. ✅
- Message collapse shrinks to subject (one-line height) → Task 3 Steps 6, 8. ✅
- Default expanded; no persistence per-file or per-commit → toggles instantiate `expanded=True` each time `make_file_block` runs; `_msg_toggle` keeps its state between commit loads (acceptable per spec). ✅
- `_set_empty_state` hides the whole panel → Task 3 Step 7. ✅
- Empty-on-error clears cached heights → Task 3 Step 9. ✅
- Tests: toggle behavior, file-block collapse, message height switch → Tasks 1, 2, 3. ✅

**Placeholder scan:** none — every step has full code or exact commands.

**Type/method consistency:**
- `_CollapseToggle.state_changed = Signal(bool)` matches the slot signatures in both call sites (`_set_expanded(expanded: bool)` and `_on_msg_toggle(expanded: bool)`).
- `_CollapseToggle.is_expanded() -> bool` is used in Task 3 Step 8 (`if self._msg_toggle.is_expanded() else ...`) — matches the definition in Task 1.
- Imports: `_CollapseToggle` imported in both `diff_block.py` and `diff.py`. ✅
