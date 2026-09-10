# Unified Commit-Detail Scroll — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `DiffWidget`'s three independent scroll surfaces (top header, file list, diff content) with one unified vertical scroll that has a sticky state banner and a sticky `FileNavigatorWidget` which transforms from a vertical list at scroll = 0 into a horizontal pill strip when pinned.

**Architecture:** A new `FileNavigatorWidget` exposes two interchangeable shapes (list / pill) backed by a shared selection model. `DiffWidget` is restructured around a single `QScrollArea`; the navigator lives in one of two stable slots (`_flow_slot` inside the scroll content, `_pin_slot` outside) and is reparented between them by a `_StickyPinController` that observes scroll value vs. `_flow_slot.geometry().top()` with 4 px hysteresis. `ViewportBlockLoader` is re-pointed at the new scroll area.

**Tech Stack:** Python, PySide6, pygit2, pytest, pytest-qt, uv.

**Spec:** `docs/superpowers/specs/2026-05-04-unified-commit-detail-scroll-design.md`

---

## File Map

| Path | Action |
|------|--------|
| `git_gui/presentation/widgets/file_list_view.py` | Modify (add `FileDeltaDelegate`, `DELTA_LABEL`, `BADGE_SIZE`, `BADGE_GAP` — moved from `diff.py`) |
| `git_gui/presentation/widgets/file_navigator.py` | Create |
| `git_gui/presentation/widgets/diff.py` | Modify (remove delegate constants/class; replace splitter/file_view/diff_scroll with unified scroll architecture; wire `_StickyPinController`) |
| `tests/presentation/widgets/test_file_list_view.py` | Modify if exists, else add minimal coverage of relocated delegate (only if it has no current tests — verify in Task 1) |
| `tests/presentation/widgets/test_file_navigator.py` | Create |
| `tests/presentation/widgets/test_diff_widget.py` | Modify (update existing tests for new attributes; add sticky-pin, auto-highlight, and pin-conditional-scroll tests) |

Untouched: domain (`entities.py`, `ports.py`), application (`commands.py`, `queries.py`), infrastructure (pygit2 ops), `presentation/models/diff_model.py`, `presentation/widgets/commit_detail.py`, `presentation/widgets/diff_block.py`, `presentation/widgets/viewport_block_loader.py`, `presentation/widgets/working_tree.py`, `presentation/main_window/right_panel.py`, all theme files.

---

## Task 1: Relocate `FileDeltaDelegate` from `diff.py` to `file_list_view.py`

This is a paving refactor — no behavioral change. The delegate currently lives in `diff.py` as a private class but will be needed by both `DiffWidget` (during the transition period) and the new `FileNavigatorWidget`. Move it to `file_list_view.py` so both can import it without circular dependencies.

**Files:**
- Modify: `git_gui/presentation/widgets/file_list_view.py`
- Modify: `git_gui/presentation/widgets/diff.py`

### 1.1 Verify baseline tests pass

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest tests/ -v`

Expected: all tests pass. Note the count.

If anything fails on a clean tree, stop and surface it.

### 1.2 Move constants and class

- [ ] **Step 2: Append constants and `FileDeltaDelegate` to `file_list_view.py`**

Open `git_gui/presentation/widgets/file_list_view.py`. After the existing `FileListView` class (after line 54), append:

```python


# ── Delegate for FileListView's default look ─────────────────────────────
# Moved here from diff.py so FileListView and FileNavigatorWidget can both
# use it without circular imports.

from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QBrush, QPainter
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem

from git_gui.presentation.theme import get_theme_manager


DELTA_LABEL = {
    "modified": "M",
    "added":    "A",
    "deleted":  "D",
    "renamed":  "R",
    "unknown":  "?",
}

BADGE_SIZE = 20
BADGE_GAP = 6


class FileDeltaDelegate(QStyledItemDelegate):
    """Paints a colored delta badge plus the file path for a FileListView row."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        rect = option.rect

        if option.state & QStyle.State_Selected:
            painter.fillRect(rect, get_theme_manager().current.colors.as_qcolor("primary"))

        fs = index.data(Qt.UserRole)
        delta = fs.delta if fs else "unknown"
        label = DELTA_LABEL.get(delta, "?")

        badge_x = rect.left() + 4
        badge_y = rect.top() + (rect.height() - BADGE_SIZE) // 2
        badge_rect = QRect(badge_x, badge_y, BADGE_SIZE, BADGE_SIZE)
        painter.setBrush(QBrush(get_theme_manager().current.colors.status_color(delta)))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(badge_rect, 3, 3)

        painter.setPen(get_theme_manager().current.colors.as_qcolor("on_badge"))
        painter.drawText(badge_rect, Qt.AlignCenter, label)

        text_x = badge_x + BADGE_SIZE + BADGE_GAP
        text_rect = QRect(text_x, rect.top(), rect.right() - text_x, rect.height())
        painter.setPen(option.palette.text().color())
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, index.data(Qt.DisplayRole) or "")

        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        return QSize(option.rect.width(), max(BADGE_SIZE + 8, option.fontMetrics.height() + 8))
```

(`QStyle` is already imported at the top of the file from line 5; the new imports above only add `QRect`, `QSize`, `QBrush`, `QPainter`, `QStyledItemDelegate`, `QStyleOptionViewItem`, and `get_theme_manager`.)

- [ ] **Step 3: Remove constants and class from `diff.py`**

Open `git_gui/presentation/widgets/diff.py`. Delete lines 22–69 (the `_DELTA_LABEL` dict, `BADGE_SIZE`, `BADGE_GAP`, and the `_FileDeltaDelegate` class). Also remove the now-unused imports `QBrush`, `QPainter`, `QStyledItemDelegate`, `QStyleOptionViewItem`, `QRect`, `QSize` from the imports block at the top — but keep them if other code in the file still uses them. Verify with a grep after this step.

- [ ] **Step 4: Update `diff.py` to import from `file_list_view`**

In `diff.py`, find the line:

```python
from git_gui.presentation.widgets.file_list_view import FileListView as _FileListView
```

Replace with:

```python
from git_gui.presentation.widgets.file_list_view import FileListView as _FileListView, FileDeltaDelegate
```

- [ ] **Step 5: Update `diff.py` callsite that constructs the delegate**

Find the line that constructs the delegate (around line 130 in the original):

```python
self._file_view.setItemDelegate(_FileDeltaDelegate(self._file_view))
```

Replace with:

```python
self._file_view.setItemDelegate(FileDeltaDelegate(self._file_view))
```

- [ ] **Step 6: Verify no remaining `_FileDeltaDelegate` references**

Run: `rtk grep -n "_FileDeltaDelegate\|_DELTA_LABEL" git_gui/ tests/`

Expected: no matches. If `BADGE_SIZE` or `BADGE_GAP` matches in `diff.py`, those should also be removed (they were defined but only used by the delegate). Verify and clean up.

### 1.3 Verify

- [ ] **Step 7: Run the test suite**

Run: `uv run pytest tests/ -v`

Expected: all tests pass with the same count as Step 1.

- [ ] **Step 8: Sanity-import**

Run: `uv run python -c "from git_gui.presentation.widgets.file_list_view import FileDeltaDelegate, FileListView; from git_gui.presentation.widgets.diff import DiffWidget; print('ok')"`

Expected: prints `ok`.

### 1.4 Commit

- [ ] **Step 9: Stage and commit**

```bash
rtk git add git_gui/presentation/widgets/file_list_view.py git_gui/presentation/widgets/diff.py
rtk git commit -m "$(cat <<'EOF'
refactor(file_list_view): move FileDeltaDelegate from diff.py

Pave the way for FileNavigatorWidget by relocating the delta-badge
delegate (and its DELTA_LABEL/BADGE_SIZE/BADGE_GAP constants) into
file_list_view.py. No behavioral change — DiffWidget still constructs
the same delegate the same way, just from the new import location.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds.

---

## Task 2: Create `FileNavigatorWidget` — list mode

Create the new widget with a `QStackedLayout` and only the list-mode child wired up. Pill mode is added in Task 3. The widget must expose the same selection-signal contract `DiffWidget` currently relies on (`currentChanged`, `deselected`).

**Files:**
- Create: `git_gui/presentation/widgets/file_navigator.py`
- Create: `tests/presentation/widgets/test_file_navigator.py`

### 2.1 Write the failing tests

- [ ] **Step 1: Create the test file**

Create `tests/presentation/widgets/test_file_navigator.py` with content:

```python
"""Tests for FileNavigatorWidget."""
from __future__ import annotations

import pytest

from git_gui.domain.entities import FileStatus
from git_gui.presentation.models.diff_model import DiffModel
from git_gui.presentation.widgets.file_navigator import FileNavigatorWidget, NavMode


@pytest.fixture
def files():
    return [
        FileStatus(path="a.py", status="staged", delta="modified"),
        FileStatus(path="b.py", status="staged", delta="added"),
        FileStatus(path="c.py", status="staged", delta="deleted"),
    ]


@pytest.fixture
def navigator(qtbot, files):
    model = DiffModel(files)
    widget = FileNavigatorWidget(model)
    qtbot.addWidget(widget)
    widget.show()
    return widget, model


def test_default_mode_is_list(navigator):
    widget, _ = navigator
    assert widget.mode() == NavMode.LIST
    assert widget._list_view.isVisible()


def test_set_mode_list_shows_list_view(navigator):
    widget, _ = navigator
    widget.set_mode(NavMode.LIST)
    assert widget._stack.currentWidget() is widget._list_view


def test_selection_model_is_list_views(navigator):
    widget, _ = navigator
    assert widget.selection_model is widget._list_view.selectionModel()


def test_currentChanged_signal_propagates_from_list_view(navigator, qtbot):
    widget, model = navigator
    received = []
    widget.currentChanged.connect(lambda cur, prev: received.append(cur.row()))

    idx = model.index(1)
    widget.selection_model.setCurrentIndex(idx, widget.selection_model.SelectionFlag.ClearAndSelect)

    assert received == [1]


def test_deselected_signal_propagates_from_list_view(navigator, qtbot):
    widget, model = navigator
    received = []
    widget.deselected.connect(lambda: received.append(True))

    widget._list_view.deselected.emit()

    assert received == [True]
```

- [ ] **Step 2: Run the tests — they should fail with import errors**

Run: `uv run pytest tests/presentation/widgets/test_file_navigator.py -v`

Expected: collection-time `ImportError` (the module does not exist yet).

### 2.2 Implement minimal FileNavigatorWidget (list mode only)

- [ ] **Step 3: Create `file_navigator.py` with list-mode implementation**

Create `git_gui/presentation/widgets/file_navigator.py` with content:

```python
"""FileNavigatorWidget — vertical list / horizontal pill strip for files in a commit.

Wraps a FileListView and (in pill mode, see Task 3) a horizontal strip of pill
buttons. Both share the same selection model so click-to-filter works
identically regardless of which mode is active.

Mode-switch and active-file highlight are driven externally — by
DiffWidget's _StickyPinController in the case of pin/unpin, and by scroll-
based auto-highlight logic.
"""
from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QItemSelectionModel, QModelIndex, Qt, Signal
from PySide6.QtWidgets import QListView, QStackedLayout, QWidget

from git_gui.presentation.models.diff_model import DiffModel
from git_gui.presentation.widgets.file_list_view import FileDeltaDelegate, FileListView


class NavMode(Enum):
    LIST = 0
    PILL = 1


class FileNavigatorWidget(QWidget):
    """Two-shape file navigator backed by a shared QItemSelectionModel."""

    # Re-exposes signals from the shared selection model + list view so callers
    # don't have to know the internal structure.
    currentChanged = Signal(QModelIndex, QModelIndex)
    deselected = Signal()

    def __init__(self, model: DiffModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._model = model

        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)

        # ── List mode ────────────────────────────────────────────────────────
        self._list_view = FileListView()
        self._list_view.setEditTriggers(QListView.NoEditTriggers)
        self._list_view.setModel(model)
        self._list_view.setItemDelegate(FileDeltaDelegate(self._list_view))
        self._stack.addWidget(self._list_view)

        # Pill mode placeholder (Task 3 fills this in).
        self._pill_root: QWidget | None = None

        # Wire signal forwarding.
        self._list_view.selectionModel().currentChanged.connect(self.currentChanged.emit)
        self._list_view.deselected.connect(self.deselected.emit)

    # ── Public API ──────────────────────────────────────────────────────────

    @property
    def selection_model(self) -> QItemSelectionModel:
        return self._list_view.selectionModel()

    def mode(self) -> NavMode:
        idx = self._stack.currentIndex()
        return NavMode.LIST if idx == 0 else NavMode.PILL

    def set_mode(self, mode: NavMode) -> None:
        self._stack.setCurrentIndex(mode.value)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/presentation/widgets/test_file_navigator.py -v`

Expected: all five tests pass.

### 2.3 Verify

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest tests/ -v`

Expected: all tests pass (existing tests are unaffected; new tests pass).

### 2.4 Commit

- [ ] **Step 6: Stage and commit**

```bash
rtk git add git_gui/presentation/widgets/file_navigator.py tests/presentation/widgets/test_file_navigator.py
rtk git commit -m "$(cat <<'EOF'
feat(file_navigator): create FileNavigatorWidget with list mode

Introduce a QStackedLayout-based widget that wraps FileListView and
re-exposes its selection signals. Pill mode is stubbed (set_mode(PILL)
does nothing visible yet) — populated in the next task. The shared
selection model is the list view's, by design.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds.

---

## Task 3: Add pill mode + `set_active_file` to `FileNavigatorWidget`

Add the horizontal pill strip as the second stack child. Pills are `QPushButton(checkable=True)` with a delta-color icon. Click on a pill updates the shared selection model. The "All" pill is a synthetic non-model row that calls `selection_model.clearSelection()`. `set_active_file(path)` updates a visual highlight on the matching pill *without* firing selection-model changes.

**Files:**
- Modify: `git_gui/presentation/widgets/file_navigator.py`
- Modify: `tests/presentation/widgets/test_file_navigator.py`

### 3.1 Write the failing tests

- [ ] **Step 1: Append pill-mode tests to `test_file_navigator.py`**

Open `tests/presentation/widgets/test_file_navigator.py`. After the existing `test_deselected_signal_propagates_from_list_view`, append:

```python


# ── Pill mode ──────────────────────────────────────────────────────────


def test_set_mode_pill_shows_pill_strip(navigator):
    widget, _ = navigator
    widget.set_mode(NavMode.PILL)
    assert widget.mode() == NavMode.PILL
    assert widget._stack.currentWidget() is widget._pill_root


def test_pill_strip_has_all_pill_plus_one_per_file(navigator):
    widget, _ = navigator
    widget.set_mode(NavMode.PILL)
    # 1 "All" pill + 3 file pills (a.py, b.py, c.py)
    assert len(widget._pill_buttons) == 3
    assert widget._all_pill is not None


def test_clicking_pill_updates_shared_selection(navigator, qtbot):
    widget, model = navigator
    widget.set_mode(NavMode.PILL)

    # Click the pill for "b.py" (row 1)
    pill = widget._pill_buttons["b.py"]
    pill.click()

    assert widget.selection_model.currentIndex().row() == 1
    assert widget.selection_model.hasSelection()


def test_clicking_all_pill_clears_selection(navigator, qtbot):
    widget, model = navigator
    widget.set_mode(NavMode.PILL)

    # First select something via the list view's selection model
    widget.selection_model.setCurrentIndex(
        model.index(1),
        widget.selection_model.SelectionFlag.ClearAndSelect,
    )
    assert widget.selection_model.hasSelection()

    # Then click "All"
    widget._all_pill.click()

    assert not widget.selection_model.hasSelection()


def test_set_active_file_marks_corresponding_pill_checked(navigator):
    widget, _ = navigator
    widget.set_mode(NavMode.PILL)

    widget.set_active_file("c.py")

    assert widget._pill_buttons["c.py"].isChecked()
    assert not widget._pill_buttons["a.py"].isChecked()
    assert not widget._pill_buttons["b.py"].isChecked()


def test_set_active_file_does_not_change_selection(navigator):
    widget, _ = navigator
    widget.set_mode(NavMode.PILL)

    widget.set_active_file("a.py")

    assert not widget.selection_model.hasSelection()


def test_set_active_file_none_marks_all_pill(navigator):
    widget, _ = navigator
    widget.set_mode(NavMode.PILL)

    widget.set_active_file(None)

    assert widget._all_pill.isChecked()
    assert not any(p.isChecked() for p in widget._pill_buttons.values())


def test_model_reset_rebuilds_pill_strip(navigator, qtbot):
    from git_gui.domain.entities import FileStatus
    widget, model = navigator
    widget.set_mode(NavMode.PILL)

    new_files = [FileStatus(path="x.py", status="staged", delta="modified")]
    model.reload(new_files)

    assert "x.py" in widget._pill_buttons
    assert "a.py" not in widget._pill_buttons
```

- [ ] **Step 2: Run the new tests — they should fail**

Run: `uv run pytest tests/presentation/widgets/test_file_navigator.py -v`

Expected: the eight new tests fail (the existing five from Task 2 still pass). Failure mode: `AttributeError: ... '_pill_root'` or similar — pill mode isn't implemented yet.

### 3.2 Implement pill mode

- [ ] **Step 3: Add pill-mode constants and helpers to `file_navigator.py`**

Open `git_gui/presentation/widgets/file_navigator.py`. After the `NavMode` enum and before the `FileNavigatorWidget` class, add:

```python
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QScrollArea

from git_gui.presentation.theme import connect_widget, get_theme_manager


def _delta_dot_icon(delta: str, diameter: int = 8) -> QIcon:
    """Generate a circle-icon pixmap colored by the file's delta status."""
    pix = QPixmap(diameter, diameter)
    pix.fill(QColor(0, 0, 0, 0))  # transparent
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    color = get_theme_manager().current.colors.status_color(delta)
    painter.setBrush(color)
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(0, 0, diameter, diameter)
    painter.end()
    return QIcon(pix)
```

- [ ] **Step 4: Build the pill strip in `__init__`**

In `FileNavigatorWidget.__init__`, replace the line:

```python
        # Pill mode placeholder (Task 3 fills this in).
        self._pill_root: QWidget | None = None
```

with:

```python
        # ── Pill mode ────────────────────────────────────────────────────────
        self._pill_root = QScrollArea()
        self._pill_root.setWidgetResizable(True)
        self._pill_root.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._pill_root.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._pill_root.setFrameShape(QScrollArea.NoFrame)

        self._pill_container = QWidget()
        self._pill_layout = QHBoxLayout(self._pill_container)
        self._pill_layout.setContentsMargins(4, 4, 4, 4)
        self._pill_layout.setSpacing(4)
        self._pill_layout.addStretch(1)  # right-side filler
        self._pill_root.setWidget(self._pill_container)
        self._stack.addWidget(self._pill_root)

        # "All" synthetic pill (always present, at index 0).
        self._all_pill = QPushButton("All")
        self._all_pill.setCheckable(True)
        self._all_pill.setChecked(True)
        self._all_pill.clicked.connect(self._on_all_pill_clicked)
        self._pill_layout.insertWidget(0, self._all_pill)

        self._pill_buttons: dict[str, QPushButton] = {}
        self._build_pills()
        model.modelReset.connect(self._build_pills)

        # Sync pill check state from selection model changes (so list-view
        # clicks update pill highlight too).
        self._list_view.selectionModel().currentChanged.connect(self._sync_pills_to_selection)
        self._list_view.deselected.connect(self._sync_pills_to_selection_cleared)

        connect_widget(self, rebuild=self._restyle_pills)
        self._restyle_pills()
```

- [ ] **Step 5: Add the pill-management methods**

After the `set_mode` method, append to the class:

```python
    # ── Pill management ─────────────────────────────────────────────────────

    def _build_pills(self) -> None:
        """Tear down current per-file pills and rebuild from the model."""
        # Remove existing per-file pills (skip the "All" pill at index 0 and
        # the trailing stretch).
        for btn in list(self._pill_buttons.values()):
            self._pill_layout.removeWidget(btn)
            btn.deleteLater()
        self._pill_buttons.clear()

        for row in range(self._model.rowCount()):
            idx = self._model.index(row)
            fs = self._model.data(idx, Qt.UserRole)
            if fs is None:
                continue
            btn = QPushButton(fs.path)
            btn.setIcon(_delta_dot_icon(fs.delta))
            btn.setCheckable(True)
            btn.setChecked(False)
            btn.clicked.connect(lambda _checked=False, r=row: self._on_pill_clicked(r))
            # Insert before the stretch (which is at the end).
            insert_at = self._pill_layout.count() - 1
            self._pill_layout.insertWidget(insert_at, btn)
            self._pill_buttons[fs.path] = btn

        # Reset highlight to "All".
        self._all_pill.setChecked(not self.selection_model.hasSelection())

    def _on_pill_clicked(self, row: int) -> None:
        idx = self._model.index(row)
        self.selection_model.setCurrentIndex(
            idx, QItemSelectionModel.SelectionFlag.ClearAndSelect
        )

    def _on_all_pill_clicked(self) -> None:
        self.selection_model.clearSelection()
        self._list_view.setCurrentIndex(QModelIndex())
        self._sync_pills_to_selection_cleared()
        self.deselected.emit()

    def _sync_pills_to_selection(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if not current.isValid():
            self._sync_pills_to_selection_cleared()
            return
        fs = self._model.data(current, Qt.UserRole)
        active_path = fs.path if fs else None
        for path, btn in self._pill_buttons.items():
            btn.setChecked(path == active_path)
        self._all_pill.setChecked(active_path is None)

    def _sync_pills_to_selection_cleared(self) -> None:
        for btn in self._pill_buttons.values():
            btn.setChecked(False)
        self._all_pill.setChecked(True)

    # ── set_active_file (visual-only highlight; does not change selection) ──

    def set_active_file(self, path: str | None) -> None:
        """Visually highlight a pill (and ensure it is on screen) without
        changing the selection model. Used by auto-highlight on scroll."""
        if path is None:
            self._all_pill.setChecked(True)
            for btn in self._pill_buttons.values():
                btn.setChecked(False)
            return

        self._all_pill.setChecked(False)
        active_btn = self._pill_buttons.get(path)
        for p, btn in self._pill_buttons.items():
            btn.setChecked(p == path)
        if active_btn is not None:
            self._pill_root.ensureWidgetVisible(active_btn)

    # ── Theming ─────────────────────────────────────────────────────────────

    def _restyle_pills(self) -> None:
        c = get_theme_manager().current.colors
        bg = c.surface_container_high
        outline = c.outline
        on_surface = c.on_surface
        primary = c.primary
        on_primary = c.on_primary

        pill_qss = (
            f"QPushButton {{ background: {bg}; color: {on_surface}; "
            f"border: 1px solid {outline}; border-radius: 12px; "
            f"padding: 2px 10px; }} "
            f"QPushButton:checked {{ background: {primary}; color: {on_primary}; "
            f"border-color: {primary}; }}"
        )
        self._all_pill.setStyleSheet(pill_qss)
        for btn in self._pill_buttons.values():
            btn.setStyleSheet(pill_qss)
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/presentation/widgets/test_file_navigator.py -v`

Expected: all 13 tests pass (5 from Task 2 + 8 from Task 3).

### 3.3 Verify

- [ ] **Step 7: Run the full test suite**

Run: `uv run pytest tests/ -v`

Expected: all tests pass.

### 3.4 Commit

- [ ] **Step 8: Stage and commit**

```bash
rtk git add git_gui/presentation/widgets/file_navigator.py tests/presentation/widgets/test_file_navigator.py
rtk git commit -m "$(cat <<'EOF'
feat(file_navigator): add pill mode with shared selection

Pill strip uses QPushButton (checkable) with a delta-color icon. The
"All" pill is a synthetic non-model row that clears selection on click.
Selection model is shared across list and pill views — click in either
updates the same selection. set_active_file is a visual-only highlight
used by auto-highlight on scroll (does not fire selection changes).

Theming pulls all colors from MD3 tokens (surface_container_high,
primary, on_primary, outline, on_surface). Reacts to theme changes
via connect_widget(rebuild=_restyle_pills).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds.

---

## Task 4: Refactor `DiffWidget` to unified scroll architecture

Replace `_file_view`, `_splitter`, `_diff_scroll` with `_scroll_area` + `_pin_slot` + `_flow_slot` + `_file_navigator`. The state banner becomes a sibling of the scroll area in the outer layout. `_loader` is re-pointed at `_scroll_area`. Existing tests are updated to assert on the new attributes. The pin/unpin logic and auto-highlight come in Tasks 5 and 6 — at the end of Task 4, the navigator stays in `_flow_slot` permanently and is always in `LIST` mode, so behavior is "everything scrolls together as one column" but without sticky pin yet.

**Files:**
- Modify: `git_gui/presentation/widgets/diff.py`
- Modify: `tests/presentation/widgets/test_diff_widget.py`

### 4.1 Update existing tests first

- [ ] **Step 1: Replace `_splitter` assertions in `test_diff_widget.py`**

Open `tests/presentation/widgets/test_diff_widget.py`. Make these substitutions:

In `test_load_commit_shows_panels` (around line 58–68), replace:

```python
    assert widget._detail.isVisible()
    assert widget._msg_view.isVisible()
    assert widget._splitter.isVisible()
```

with:

```python
    assert widget._detail.isVisible()
    assert widget._msg_view.isVisible()
    assert widget._scroll_area.isVisible()
    assert widget._file_navigator.isVisible()
```

In `test_load_commit_error_hides_panels` (around line 74–84), replace:

```python
    assert not widget._detail.isVisible()
    assert not widget._msg_view.isVisible()
    assert not widget._splitter.isVisible()
```

with:

```python
    assert not widget._detail.isVisible()
    assert not widget._msg_view.isVisible()
    assert not widget._scroll_area.isVisible()
    assert not widget._file_navigator.isVisible()
```

In `test_set_buses_none_enters_empty_state` (around line 90–103), replace both:

```python
    assert widget._splitter.isVisible()
```

with:

```python
    assert widget._scroll_area.isVisible()
```

and:

```python
    assert not widget._detail.isVisible()
    assert not widget._msg_view.isVisible()
    assert not widget._splitter.isVisible()
```

with:

```python
    assert not widget._detail.isVisible()
    assert not widget._msg_view.isVisible()
    assert not widget._scroll_area.isVisible()
    assert not widget._file_navigator.isVisible()
```

`test_clear_blocks_clears_loader` does not reference `_splitter`, so it stays unchanged in this step. (It will keep working because `_loader._block_refs`, `_loaded_paths`, and `_diff_map` are loader-internal.)

- [ ] **Step 2: Run the modified tests — expect failure**

Run: `uv run pytest tests/presentation/widgets/test_diff_widget.py -v`

Expected: tests fail with `AttributeError: ... '_scroll_area'` and `AttributeError: ... '_file_navigator'` because `DiffWidget` doesn't have those attributes yet.

### 4.2 Implement the new layout

- [ ] **Step 3: Update imports in `diff.py`**

Open `git_gui/presentation/widgets/diff.py`. In the imports block, ensure these are present (some may already be):

```python
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListView, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)
```

Remove `QSplitter` from the import list (no longer used).

Add:

```python
from git_gui.presentation.widgets.file_navigator import FileNavigatorWidget, NavMode
```

Remove the now-unused `from git_gui.presentation.widgets.file_list_view import FileListView as _FileListView, FileDeltaDelegate` import line (the file navigator owns the list view + delegate now).

- [ ] **Step 4: Replace `__init__`'s file/diff/splitter section**

In `DiffWidget.__init__`, find the block that constructs `_file_view`, `_diff_scroll`, `_diff_container`, `_diff_layout`, `_diff_model`, the selection wiring, and `_splitter` (roughly lines 127–164 of the post-Task-1 file). Replace from the `# ── Row 3: file list ──` comment through `self._splitter.setStretchFactor(1, 1)` with:

```python
        # ── Diff container (will live inside the unified scroll area) ────────
        self._diff_container = QWidget()
        self._diff_layout = QVBoxLayout(self._diff_container)
        self._diff_layout.setContentsMargins(0, 4, 0, 4)
        self._diff_layout.setSpacing(8)

        # ── Shared file model + navigator ────────────────────────────────────
        self._diff_model = DiffModel([])
        self._file_navigator = FileNavigatorWidget(self._diff_model)
        self._file_navigator.currentChanged.connect(self._on_file_selected)
        self._file_navigator.deselected.connect(self._on_file_deselected)

        # ── Unified scroll area + slots ──────────────────────────────────────
        # _flow_slot: receives _file_navigator while unpinned (in flow inside
        #   the scroll content, between the message and the diff blocks).
        # _pin_slot:  receives _file_navigator while pinned (out of scroll, in
        #   the outer layout above _scroll_area).
        # Only one slot holds the navigator at any time.
        self._flow_slot = QWidget()
        flow_slot_layout = QVBoxLayout(self._flow_slot)
        flow_slot_layout.setContentsMargins(0, 0, 0, 0)
        flow_slot_layout.setSpacing(0)
        flow_slot_layout.addWidget(self._file_navigator)

        self._pin_slot = QWidget()
        pin_slot_layout = QVBoxLayout(self._pin_slot)
        pin_slot_layout.setContentsMargins(0, 0, 0, 0)
        pin_slot_layout.setSpacing(0)

        self._scroll_content = QWidget()
        scroll_content_layout = QVBoxLayout(self._scroll_content)
        scroll_content_layout.setContentsMargins(0, 0, 0, 0)
        scroll_content_layout.setSpacing(8)
        scroll_content_layout.addWidget(self._detail)
        scroll_content_layout.addWidget(self._msg_view)
        scroll_content_layout.addWidget(self._flow_slot)
        scroll_content_layout.addWidget(self._diff_container)
        scroll_content_layout.addStretch(1)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QScrollArea.NoFrame)
        self._scroll_area.setWidget(self._scroll_content)

        # Re-point the lazy diff loader at the unified scroll area.
        self._loader = ViewportBlockLoader(self._scroll_area, self._realize_block)
```

- [ ] **Step 5: Replace the outer layout assembly**

In `DiffWidget.__init__`, find the outer layout construction (the block starting `layout = QVBoxLayout(self)` near the end of `__init__`) and replace it with:

```python
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        layout.addWidget(self._state_banner, 0)
        layout.addWidget(self._pin_slot, 0)
        layout.addWidget(self._scroll_area, 1)
```

Note: `_state_banner` is constructed earlier in `__init__` exactly as today; this step just confirms it goes in the outer layout above `_pin_slot` and `_scroll_area`. Remove the obsolete `layout.addWidget(self._detail, 0)`, `layout.addWidget(self._msg_view, 0)`, and `layout.addWidget(self._splitter, 1)` lines if they're still present. Remove any trailing `layout.addStretch()` (the scroll area should fill the panel — no extra stretch).

- [ ] **Step 6: Update `_set_empty_state`**

Find the existing `_set_empty_state` method:

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
        self._detail.setVisible(not empty)
        self._msg_view.setVisible(not empty)
        self._file_navigator.setVisible(not empty)
        self._diff_container.setVisible(not empty)
        self._scroll_area.setVisible(not empty)
```

- [ ] **Step 7: Update `set_buses` to clear the new structure**

Find `set_buses`:

```python
    def set_buses(self, queries: QueryBus | None, commands: CommandBus | None) -> None:
        self._queries = queries
        self._current_oid = None
        self._detail.clear()
        self._msg_view.clear()
        self._diff_model.reload([])
        self._clear_blocks()
        self._set_empty_state(True)
        self.update_state_banner("CLEAN")
```

No changes needed here — `self._diff_model.reload([])` already triggers the navigator's `_build_pills`, and `_clear_blocks` operates on `_diff_layout` which is unchanged.

- [ ] **Step 8: Update `_render_single_file` to scroll in the new scroll area**

Find `_render_single_file`:

```python
    def _render_single_file(self, path: str, hunks) -> None:
        """Clear and render one file as a bordered block."""
        self._refresh_submodule_paths()
        self._clear_blocks()
        if self._loader:
            self._loader.clear()
        block = self._build_file_block(path, hunks)
        self._diff_layout.addWidget(block)
        self._diff_layout.addStretch()
        self._diff_scroll.verticalScrollBar().setValue(0)
```

Replace the last line `self._diff_scroll.verticalScrollBar().setValue(0)` with:

```python
        self._scroll_area.verticalScrollBar().setValue(0)
```

(Pin-conditional scroll behavior is added in Task 7. For now, we keep `setValue(0)` — i.e., always reset to top of panel — which matches today's diff-scroll-to-zero behavior in spirit.)

- [ ] **Step 9: Update `_render_all_files` to scroll in the new scroll area**

Find `_render_all_files`:

```python
        self._diff_layout.addStretch()
        self._diff_scroll.verticalScrollBar().setValue(0)

        self._loader.set_blocks(block_refs)
```

Replace `self._diff_scroll.verticalScrollBar().setValue(0)` with:

```python
        self._scroll_area.verticalScrollBar().setValue(0)
```

- [ ] **Step 10: Update `_clear_blocks` if it references `_diff_scroll`**

Run: `rtk grep -n "_diff_scroll\|_splitter\|_file_view\b" git_gui/presentation/widgets/diff.py`

Expected: no remaining references. If anything remains, fix it (it's a missed reference from the refactor).

- [ ] **Step 11: Remove `eventFilter` reference to `_msg_view.viewport()` if intact, leave alone otherwise**

The `eventFilter` method that blocks mouse interaction on `_msg_view.viewport()` is unchanged in this task. Verify it's still wired up — `self._msg_view.viewport().installEventFilter(self)` should still be in `__init__`. No edit needed.

### 4.3 Verify

- [ ] **Step 12: Run the diff widget tests**

Run: `uv run pytest tests/presentation/widgets/test_diff_widget.py -v`

Expected: all four existing tests pass with the updated assertions.

- [ ] **Step 13: Run the full test suite**

Run: `uv run pytest tests/ -v`

Expected: all tests pass.

- [ ] **Step 14: Sanity-launch the app**

Run: `uv run python main.py`

Expected: the app opens; clicking a commit shows the unified-scroll panel (state banner, commit info, message, vertical file list, diff blocks — all in one scrolling column with a single scrollbar). No splitter handle. No two scrollbars.

### 4.4 Commit

- [ ] **Step 15: Stage and commit**

```bash
rtk git add git_gui/presentation/widgets/diff.py tests/presentation/widgets/test_diff_widget.py
rtk git commit -m "$(cat <<'EOF'
refactor(diff): unify commit-detail panel into one scroll area

Replace QSplitter + nested diff QScrollArea with a single outer
QScrollArea whose content is [_detail, _msg_view, _flow_slot,
_diff_container]. _flow_slot holds FileNavigatorWidget (in LIST mode);
_pin_slot is empty for now (used by the upcoming sticky pin controller).

State banner moves to a sibling of the scroll area in the outer layout.
ViewportBlockLoader is re-pointed at the unified scroll area. Render
helpers reset scroll via the new scroll bar. Existing visibility tests
updated to reference _scroll_area / _file_navigator instead of
_splitter / _file_view.

No sticky-pin or auto-highlight yet — those land in subsequent commits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds.

---

## Task 5: Add `_StickyPinController` for pin/unpin

Implement the controller that watches the unified scroll bar and reparents `_file_navigator` between `_flow_slot` and `_pin_slot`, also flipping its mode between `LIST` and `PILL`. Add tests for threshold computation, pin/unpin transitions, hysteresis, recompute triggers (resize, model reset), and force-unpin on error.

**Files:**
- Modify: `git_gui/presentation/widgets/diff.py`
- Modify: `tests/presentation/widgets/test_diff_widget.py`

### 5.1 Write the failing tests

- [ ] **Step 1: Append controller tests to `test_diff_widget.py`**

Open `tests/presentation/widgets/test_diff_widget.py`. At the end of the file, append:

```python


# ── 5. Sticky-pin controller ─────────────────────────────────────────


from git_gui.presentation.widgets.file_navigator import NavMode


def test_threshold_recomputes_to_flow_slot_top_after_load(diff_widget, qtbot):
    """recompute_threshold reads _flow_slot.geometry().top() and stores it."""
    widget, _ = diff_widget
    with patch("threading.Thread"):
        widget.load_commit("abc123")
    widget.adjustSize()
    widget.layout().activate()
    # Whatever value Qt computed for _flow_slot.geometry().top() must equal
    # what the controller cached during load_commit's recompute call.
    assert widget._sticky_controller._threshold == widget._flow_slot.geometry().top()


def test_pin_when_scroll_passes_threshold(diff_widget, qtbot):
    """Driving _on_scroll past _threshold reparents the navigator to _pin_slot."""
    widget, _ = diff_widget
    with patch("threading.Thread"):
        widget.load_commit("abc123")

    # Inject a known threshold so the test does not depend on Qt geometry,
    # which is unreliable for a hidden/small qtbot widget.
    widget._sticky_controller._threshold = 100
    widget._sticky_controller._on_scroll(150)

    assert widget._sticky_controller._pinned is True
    assert widget._file_navigator.parent() is widget._pin_slot
    assert widget._file_navigator.mode() == NavMode.PILL


def test_unpin_when_scroll_below_threshold_minus_hysteresis(diff_widget, qtbot):
    widget, _ = diff_widget
    with patch("threading.Thread"):
        widget.load_commit("abc123")

    widget._sticky_controller._threshold = 100
    widget._sticky_controller._on_scroll(150)
    assert widget._sticky_controller._pinned

    # Drop well below threshold (more than hysteresis = 4)
    widget._sticky_controller._on_scroll(50)

    assert widget._sticky_controller._pinned is False
    assert widget._file_navigator.parent() is widget._flow_slot
    assert widget._file_navigator.mode() == NavMode.LIST


def test_hysteresis_prevents_unpin_just_below_threshold(diff_widget, qtbot):
    widget, _ = diff_widget
    with patch("threading.Thread"):
        widget.load_commit("abc123")

    widget._sticky_controller._threshold = 100
    widget._sticky_controller._on_scroll(150)
    assert widget._sticky_controller._pinned

    # Within hysteresis (98 > threshold - 4 = 96): stay pinned
    widget._sticky_controller._on_scroll(98)
    assert widget._sticky_controller._pinned is True

    # Outside hysteresis (95 < 96): unpin
    widget._sticky_controller._on_scroll(95)
    assert widget._sticky_controller._pinned is False


def test_load_error_forces_unpin(diff_widget, qtbot):
    widget, queries = diff_widget
    with patch("threading.Thread"):
        widget.load_commit("abc123")

    widget._sticky_controller._threshold = 100
    widget._sticky_controller._on_scroll(150)
    assert widget._sticky_controller._pinned

    queries.get_commit_detail.execute.side_effect = RuntimeError("gone")
    widget.load_commit("bad_oid")

    assert widget._sticky_controller._pinned is False
    assert widget._file_navigator.parent() is widget._flow_slot
```

- [ ] **Step 2: Run the new tests — expect failures**

Run: `uv run pytest tests/presentation/widgets/test_diff_widget.py -v`

Expected: the five new tests fail (`AttributeError: ... '_sticky_controller'`).

### 5.2 Implement `_StickyPinController`

- [ ] **Step 3: Add the controller class to `diff.py`**

Open `git_gui/presentation/widgets/diff.py`. After the imports block but before `class DiffWidget`, add:

```python
class _StickyPinController:
    """Owns the pin/unpin state machine and threshold computation for DiffWidget."""

    HYSTERESIS_PX = 4

    def __init__(self, owner: "DiffWidget") -> None:
        self._owner = owner
        self._threshold = 0
        self._pinned = False

    def attach(self) -> None:
        sb = self._owner._scroll_area.verticalScrollBar()
        sb.valueChanged.connect(self._on_scroll)
        self._owner._diff_model.modelReset.connect(self.recompute_threshold)

    def recompute_threshold(self) -> None:
        self._threshold = self._owner._flow_slot.geometry().top()

    def force_unpin(self) -> None:
        if self._pinned:
            self._unpin()

    def on_owner_resize(self) -> None:
        old_pinned = self._pinned
        self.recompute_threshold()
        sb_value = self._owner._scroll_area.verticalScrollBar().value()
        if old_pinned and sb_value < self._threshold - self.HYSTERESIS_PX:
            self._unpin()
        elif not old_pinned and sb_value >= self._threshold:
            self._pin()

    def _on_scroll(self, value: int) -> None:
        if not self._pinned and value >= self._threshold:
            self._pin()
        elif self._pinned and value < self._threshold - self.HYSTERESIS_PX:
            self._unpin()

    def _pin(self) -> None:
        nav = self._owner._file_navigator
        self._owner.setUpdatesEnabled(False)
        try:
            self._owner._flow_slot.layout().removeWidget(nav)
            nav.setParent(None)
            self._owner._pin_slot.layout().addWidget(nav)
            nav.set_mode(NavMode.PILL)
            nav.show()
        finally:
            self._owner.setUpdatesEnabled(True)
        self._pinned = True

    def _unpin(self) -> None:
        nav = self._owner._file_navigator
        self._owner.setUpdatesEnabled(False)
        try:
            self._owner._pin_slot.layout().removeWidget(nav)
            nav.setParent(None)
            self._owner._flow_slot.layout().addWidget(nav)
            nav.set_mode(NavMode.LIST)
            nav.show()
        finally:
            self._owner.setUpdatesEnabled(True)
        self._pinned = False
```

- [ ] **Step 4: Wire the controller into `DiffWidget.__init__`**

In `DiffWidget.__init__`, after `self._loader = ViewportBlockLoader(self._scroll_area, self._realize_block)`, add:

```python
        # ── Sticky pin controller ────────────────────────────────────────────
        self._sticky_controller = _StickyPinController(self)
        self._sticky_controller.attach()
```

- [ ] **Step 5: Add `resizeEvent` to `DiffWidget`**

Add this method to `DiffWidget` (placement: after `eventFilter` is fine):

```python
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_sticky_controller"):
            self._sticky_controller.on_owner_resize()
```

The `hasattr` guard handles the case where `resizeEvent` fires during `__init__` before the controller exists.

- [ ] **Step 6: Recompute threshold and force unpin in `load_commit`**

In `load_commit`, after `self._render_all_files(oid)` (the last line of the success path), append:

```python

        # Threshold depends on _msg_view height + flow_slot natural height,
        # both of which have settled by now (synchronous).
        self._sticky_controller.recompute_threshold()
        self._sticky_controller.force_unpin()
```

In the `except` branch of `load_commit`, after `self._set_empty_state(True)` and before `return`, add:

```python
            self._sticky_controller.force_unpin()
```

- [ ] **Step 7: Run the controller tests**

Run: `uv run pytest tests/presentation/widgets/test_diff_widget.py -v`

Expected: all tests pass — the four original visibility tests plus the five new sticky-pin tests.

If `test_threshold_equals_flow_slot_top_after_load` fails because `_flow_slot.geometry().top()` is 0 in the test environment (Qt may not have laid out the widget yet despite `_force_layout`), update the test to call `qtbot.wait(50)` after `widget.show()` in the fixture, or assert the navigator's parent and pin state instead.

### 5.3 Verify

- [ ] **Step 8: Run the full test suite**

Run: `uv run pytest tests/ -v`

Expected: all tests pass.

- [ ] **Step 9: Manual sanity-check**

Run: `uv run python main.py`

Click any commit with at least 2 files. Verify:
- At scroll = 0, the file list shows as a vertical list under the message.
- Wheel-scrolling down past the message + file list region: the file list disappears from the scroll content and a horizontal pill strip appears at the top of the panel (above the scroll area).
- Wheel-scrolling back up: the pill strip disappears; the vertical list returns to the scroll content.

If the pill strip flashes or the navigator briefly disappears at the threshold, hysteresis may need increasing — note for follow-up but do not block this task.

### 5.4 Commit

- [ ] **Step 10: Stage and commit**

```bash
rtk git add git_gui/presentation/widgets/diff.py tests/presentation/widgets/test_diff_widget.py
rtk git commit -m "$(cat <<'EOF'
feat(diff): sticky pin for file navigator on scroll

Add _StickyPinController which observes the unified scroll bar and
reparents _file_navigator between _flow_slot (in scroll content, LIST
mode) and _pin_slot (in outer layout above scroll area, PILL mode)
when scroll value crosses _flow_slot.geometry().top(), with a 4 px
hysteresis on the unpin direction.

Threshold is recomputed on load_commit, on DiffModel.modelReset, and
on DiffWidget.resizeEvent. force_unpin is called from the load_commit
error path so a subsequent successful load starts in a known state.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds.

---

## Task 6: Auto-highlight pill on scroll (in "All" mode only)

When pinned and not filtered, walk the diff blocks on every scroll event to find which file's block is at the visible viewport top, and call `_file_navigator.set_active_file(path)`. Disabled while filtered (single-file view) or unpinned (the pill strip isn't visible).

**Files:**
- Modify: `git_gui/presentation/widgets/diff.py`
- Modify: `tests/presentation/widgets/test_diff_widget.py`

### 6.1 Write the failing tests

- [ ] **Step 1: Append auto-highlight tests to `test_diff_widget.py`**

```python


# ── 6. Auto-highlight on scroll ───────────────────────────────────────


@pytest.fixture
def multi_file_diff_widget(qtbot):
    """A DiffWidget loaded with three files for auto-highlight testing."""
    queries = _make_mock_queries()
    queries.get_commit_files.execute.return_value = [
        FileStatus(path="a.py", status="staged", delta="modified"),
        FileStatus(path="b.py", status="staged", delta="added"),
        FileStatus(path="c.py", status="staged", delta="deleted"),
    ]
    commands = MagicMock()
    widget = DiffWidget(queries, commands)
    qtbot.addWidget(widget)
    widget.show()
    with patch("threading.Thread"):
        widget.load_commit("abc123")
    widget.adjustSize()
    widget.layout().activate()
    return widget, queries


def test_auto_highlight_calls_set_active_file_when_pinned_and_unfiltered(
    multi_file_diff_widget, qtbot
):
    """When _on_scroll runs while pinned + unfiltered, the controller
    consults _find_active_file_block and calls set_active_file with its result.

    Stubbed: threshold (so we can pin without depending on real geometry) and
    _find_active_file_block (so we don't depend on file frames having real
    geometry in a hidden qtbot widget).
    """
    widget, _ = multi_file_diff_widget

    # Pin via the controller's own logic (deterministic).
    widget._sticky_controller._threshold = 100
    widget._sticky_controller._on_scroll(150)
    assert widget._sticky_controller._pinned

    # Stub the block-finder to return a known path.
    widget._sticky_controller._find_active_file_block = lambda v: "b.py"

    # Spy on set_active_file.
    calls = []
    widget._file_navigator.set_active_file = lambda p: calls.append(p)

    # Trigger another scroll event.
    widget._sticky_controller._on_scroll(200)

    assert calls == ["b.py"]


def test_auto_highlight_disabled_while_filtered(multi_file_diff_widget, qtbot):
    widget, queries = multi_file_diff_widget
    queries.get_file_diff.execute.return_value = []

    # Pin
    widget._sticky_controller._threshold = 100
    widget._sticky_controller._on_scroll(150)
    assert widget._sticky_controller._pinned

    # Filter to one file (sets the selection model)
    widget._file_navigator.selection_model.setCurrentIndex(
        widget._diff_model.index(1),
        widget._file_navigator.selection_model.SelectionFlag.ClearAndSelect,
    )

    # Stub the block-finder so we'd see calls if the gate failed.
    widget._sticky_controller._find_active_file_block = lambda v: "b.py"

    # Spy
    calls = []
    widget._file_navigator.set_active_file = lambda p: calls.append(p)

    # Scroll while filtered.
    widget._sticky_controller._on_scroll(200)

    assert calls == [], f"set_active_file should not fire while filtered; got {calls}"


def test_auto_highlight_disabled_while_unpinned(multi_file_diff_widget, qtbot):
    widget, _ = multi_file_diff_widget

    # Stay unpinned; threshold high enough that _on_scroll(50) doesn't pin.
    widget._sticky_controller._threshold = 100

    # Stub
    widget._sticky_controller._find_active_file_block = lambda v: "b.py"

    # Spy
    calls = []
    widget._file_navigator.set_active_file = lambda p: calls.append(p)

    widget._sticky_controller._on_scroll(50)

    assert widget._sticky_controller._pinned is False
    assert calls == [], f"set_active_file should not fire while unpinned; got {calls}"
```

- [ ] **Step 2: Run the new tests — expect failures**

Run: `uv run pytest tests/presentation/widgets/test_diff_widget.py -v`

Expected: the three new tests fail (auto-highlight isn't implemented).

### 6.2 Implement auto-highlight

- [ ] **Step 3: Add `_find_active_file_block` and the scroll-event integration**

In `_StickyPinController._on_scroll`, after the existing pin/unpin logic, append:

```python
        # Auto-highlight pill on scroll (All mode only, while pinned).
        if self._pinned and not self._owner._file_navigator.selection_model.hasSelection():
            active_path = self._find_active_file_block(value)
            if active_path is not None:
                self._owner._file_navigator.set_active_file(active_path)
```

Then add a method to `_StickyPinController`:

```python
    def _find_active_file_block(self, scroll_value: int) -> str | None:
        """Return the path of the file block whose top is at or just above the
        viewport's visible top. Linear scan — fine for ≤~50 files per commit.

        Coordinate math: frame.geometry() is relative to its parent
        (_diff_container). _diff_container's geometry().top() is relative to
        _scroll_content. The unified scroll value is in _scroll_content
        coords, so the frame's absolute top = container.top() + frame.top().
        """
        viewport_top = scroll_value
        container_top = self._owner._diff_container.geometry().top()
        diff_layout = self._owner._diff_layout
        for i in range(diff_layout.count()):
            item = diff_layout.itemAt(i)
            w = item.widget()
            if w is None:
                continue
            path = w.property("file_path")
            if not isinstance(path, str):
                continue
            top = container_top + w.geometry().top()
            bottom = top + w.geometry().height()
            if top <= viewport_top < bottom:
                return path
        return None
```

- [ ] **Step 4: Set the `file_path` property on each file block**

Find `_build_file_block` in `diff.py`:

```python
    def _build_file_block(self, path: str, hunks):
        ...
        frame, inner = make_file_block(path, on_header_clicked=on_click)

        for hunk in hunks:
            add_hunk_widget(...)

        return frame
```

After `frame, inner = make_file_block(...)`, add:

```python
        frame.setProperty("file_path", path)
```

Find `_build_skeleton_block` and after `frame, inner = make_file_block(...)`, add the same:

```python
        frame.setProperty("file_path", path)
```

- [ ] **Step 5: Run the auto-highlight tests**

Run: `uv run pytest tests/presentation/widgets/test_diff_widget.py -v`

Expected: all three auto-highlight tests pass. They are deterministic (each injects `_threshold` and stubs `_find_active_file_block`) so they should not depend on Qt's layout/geometry in the headless test environment.

### 6.3 Verify

- [ ] **Step 6: Run the full test suite**

Run: `uv run pytest tests/ -v`

Expected: all tests pass.

- [ ] **Step 7: Manual sanity-check**

Run: `uv run python main.py`

Click a commit with 3+ files. Scroll past the file list to pin the pill strip. Continue scrolling through the diffs. Verify:
- The active pill in the strip changes as you scroll past each file's hunks.
- If the active pill is offscreen in the strip, the strip auto-scrolls horizontally to bring it into view.
- Click "All" pill: highlight returns to "All".
- Click a specific file's pill: filter applies; auto-highlight no longer fires (pill stays highlighted on the filtered file).

### 6.4 Commit

- [ ] **Step 8: Stage and commit**

```bash
rtk git add git_gui/presentation/widgets/diff.py tests/presentation/widgets/test_diff_widget.py
rtk git commit -m "$(cat <<'EOF'
feat(diff): auto-highlight active pill on scroll

When pinned and unfiltered, every scroll-value change linearly walks
the diff layout's file frames to find the block under the visible
viewport top (using a "file_path" Qt property set on each frame in
_build_file_block / _build_skeleton_block). Calls
FileNavigator.set_active_file(path), which highlights the matching pill
visually and scrolls the pill strip horizontally to bring it into view.

set_active_file does NOT fire selection-model changes — the filter
state is unchanged. Auto-highlight skips when filtered (selection
present) or when unpinned (pill strip isn't visible anyway).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds.

---

## Task 7: Pin-conditional scroll on filter change

Modify `_render_single_file` and `_render_all_files` to scroll the unified scroll area to the start of `_diff_container` when pinned, and to leave the scroll position unchanged when unpinned. Add tests for the four cases.

**Files:**
- Modify: `git_gui/presentation/widgets/diff.py`
- Modify: `tests/presentation/widgets/test_diff_widget.py`

### 7.1 Write the failing tests

- [ ] **Step 1: Append pin-conditional-scroll tests to `test_diff_widget.py`**

```python


# ── 7. Pin-conditional scroll on filter change ───────────────────────


def test_render_single_file_while_pinned_calls_setvalue_with_diff_container_top(
    multi_file_diff_widget, qtbot
):
    """When pinned, _render_single_file scrolls to _diff_container.geometry().top()."""
    widget, _ = multi_file_diff_widget
    widget._sticky_controller._pinned = True

    sb = widget._scroll_area.verticalScrollBar()
    with patch.object(sb, "setValue") as mock_setvalue:
        widget._render_single_file("a.py", [])
        mock_setvalue.assert_called_with(widget._diff_container.geometry().top())


def test_render_single_file_while_unpinned_does_not_call_setvalue(
    multi_file_diff_widget, qtbot
):
    """When unpinned, _render_single_file leaves scroll position alone."""
    widget, _ = multi_file_diff_widget
    widget._sticky_controller._pinned = False

    sb = widget._scroll_area.verticalScrollBar()
    with patch.object(sb, "setValue") as mock_setvalue:
        widget._render_single_file("a.py", [])
        mock_setvalue.assert_not_called()


def test_render_all_files_while_pinned_calls_setvalue_with_diff_container_top(
    multi_file_diff_widget, qtbot
):
    """When pinned, _render_all_files scrolls to _diff_container.geometry().top()."""
    widget, _ = multi_file_diff_widget
    widget._sticky_controller._pinned = True

    sb = widget._scroll_area.verticalScrollBar()
    with patch.object(sb, "setValue") as mock_setvalue, patch("threading.Thread"):
        widget._render_all_files("abc123")
        mock_setvalue.assert_called_with(widget._diff_container.geometry().top())


def test_render_all_files_while_unpinned_does_not_call_setvalue(
    multi_file_diff_widget, qtbot
):
    """When unpinned, _render_all_files leaves scroll position alone."""
    widget, _ = multi_file_diff_widget
    widget._sticky_controller._pinned = False

    sb = widget._scroll_area.verticalScrollBar()
    with patch.object(sb, "setValue") as mock_setvalue, patch("threading.Thread"):
        widget._render_all_files("abc123")
        mock_setvalue.assert_not_called()
```

- [ ] **Step 2: Run the new tests — expect failures**

Run: `uv run pytest tests/presentation/widgets/test_diff_widget.py -v`

Expected: the two "while pinned" tests fail (they assert `setValue` was called with `_diff_container.geometry().top()` but production code currently calls it with `0`). The two "while unpinned" tests also fail (they assert `setValue` was NOT called, but production code calls it unconditionally with `0`).

### 7.2 Implement pin-conditional scroll

- [ ] **Step 3: Replace the scroll-reset call in `_render_single_file`**

Find in `_render_single_file`:

```python
        self._scroll_area.verticalScrollBar().setValue(0)
```

Replace with:

```python
        if self._sticky_controller._pinned:
            self._scroll_area.verticalScrollBar().setValue(
                self._diff_container.geometry().top()
            )
        # (else: leave scroll position alone — user is in unpinned, full-context view)
```

- [ ] **Step 4: Replace the scroll-reset call in `_render_all_files`**

Find in `_render_all_files`:

```python
        self._scroll_area.verticalScrollBar().setValue(0)
```

Replace with:

```python
        if self._sticky_controller._pinned:
            self._scroll_area.verticalScrollBar().setValue(
                self._diff_container.geometry().top()
            )
```

- [ ] **Step 5: Run the pin-conditional-scroll tests**

Run: `uv run pytest tests/presentation/widgets/test_diff_widget.py -v`

Expected: all four pin-conditional-scroll tests pass, plus all earlier tests still pass.

### 7.3 Verify

- [ ] **Step 6: Run the full test suite**

Run: `uv run pytest tests/ -v`

Expected: all tests pass.

- [ ] **Step 7: Manual sanity-check**

Run: `uv run python main.py`

Click a commit with 3+ files. Verify:

- At scroll = 0 (unpinned): click a file in the vertical list → diff filters; **scroll does not jump**; you can still see commit info above.
- Same: click the active row to deselect → returns to all-files diff; scroll still unchanged.
- Scroll down to pin the pill strip. Click a different file's pill → diff filters and scrolls to put the new file's first hunk just below the pill strip.
- While pinned, click "All" → all-files diff returns; scroll lands at the top of the diff section.

### 7.4 Commit

- [ ] **Step 8: Stage and commit**

```bash
rtk git add git_gui/presentation/widgets/diff.py tests/presentation/widgets/test_diff_widget.py
rtk git commit -m "$(cat <<'EOF'
feat(diff): pin-conditional scroll reset on filter change

_render_single_file and _render_all_files now reset scroll only when
pinned, and they reset to _diff_container.geometry().top() (just below
the pinned pill strip) rather than 0 (which would unpin). When unpinned
the user is in the read-as-one-page view with commit info visible —
yanking scroll on filter would push that offscreen, so we leave it alone.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds.

---

## Task 8: Manual smoke test

No code changes. End-to-end validation of the feature in the running app.

**Files:** none modified. No commit.

- [ ] **Step 1: Launch the app**

Run: `uv run python main.py`

Expected: app opens without errors.

- [ ] **Step 2: Open a repository with substantial history**

Open GitStack itself or any repo with commits that have 3+ files and multi-line messages.

- [ ] **Step 3: Verify scroll = 0 layout**

Click a commit with 5+ files. Expected:
- Top: state banner area (only visible if a merge/rebase is active — for a clean repo this will be empty/hidden).
- Below: commit detail row (avatar, author, timestamp, hash, ref badges, parents).
- Below: commit message block.
- Below: vertical file list showing each file with its delta badge.
- Below: diff content (file blocks with hunks, lazy-loaded).
- One scrollbar on the right of the panel.

- [ ] **Step 4: Verify pin transition**

Wheel-scroll down slowly. Expected:
- Commit detail and message scroll out of view normally.
- At the moment the vertical file list would scroll above the visible top of the panel, the file list disappears and a horizontal pill strip appears at the very top of the panel (above the scroll area).
- The pill strip shows: "All" pill (highlighted), one pill per file with a delta-color dot.
- No flicker between the vertical list disappearing and the pill strip appearing.

- [ ] **Step 5: Verify auto-highlight on scroll**

Continue wheel-scrolling through the diff content (still in "All" mode — no file selected). Expected:
- As scroll passes each file's first hunk, the corresponding pill in the strip becomes highlighted.
- If the highlighted pill is offscreen in the strip, the strip horizontally scrolls to bring it into view.

- [ ] **Step 6: Verify file switch via pill click while pinned**

Click any file's pill (e.g., the third file). Expected:
- The diff content filters to only that file.
- The clicked pill stays highlighted.
- Scroll position lands so the file's first hunk is the topmost diff content (just below the pinned pill strip).

- [ ] **Step 7: Verify "All" pill while pinned**

Click "All". Expected:
- Diff returns to all-files view.
- Scroll position lands at the top of the diff section (just below the pinned pill strip).

- [ ] **Step 8: Verify file switch via list click while unpinned**

Wheel-scroll back to the top of the panel. Click a file row in the vertical list. Expected:
- The diff content filters.
- Scroll position stays where it was (commit detail and message still visible above).

- [ ] **Step 9: Verify state banner stickiness**

Trigger a state banner: start a rebase that creates a conflict, OR temporarily edit `update_state_banner("REBASING")` in a Python REPL and call it on the running widget. Expected:
- The banner stays visible at the very top of the panel in both unpinned and pinned states.
- When pinned, the banner is above the pill strip; both are sticky.

- [ ] **Step 10: Verify resize**

Resize the main window while unpinned, and again while pinned. Expected:
- No crashes, no widget disappearance.
- If resize causes the threshold to change such that the current scroll value falls on a different side of the threshold, pin/unpin transitions cleanly.

- [ ] **Step 11: Verify error path**

Make `get_commit_detail` raise. Easiest way: rebase or reset the working repo to drop a commit, then click the now-missing commit in the cached graph. Expected:
- The panel clears (empty state).
- A warning is logged: `Failed to load commit ... gone`.
- No `AttributeError`. The next successful commit click loads with the navigator in `_flow_slot` and mode `LIST`.

If all 11 steps pass, the feature is verified end-to-end.

---

## Self-Review Notes

- **Spec coverage:** every section of the spec maps to a task:
  - Architecture (widget tree, slots) → Task 4.
  - `FileNavigatorWidget` (new component) → Tasks 2 + 3.
  - `_StickyPinController` (new helper) → Task 5.
  - Data flow `load_commit` → Task 4 step 6, Task 5 step 6 (threshold recompute + force_unpin).
  - Data flow filter on/off (pin-conditional) → Task 7.
  - Data flow pin/unpin → Task 5.
  - Data flow auto-highlight → Task 6.
  - State table — covered implicitly by the test matrix (pin × filter combinations).
  - Edge cases — exercised by tests + manual.
  - Theming — Task 3 step 5 (`_restyle_pills` using MD3 tokens).
  - Error handling (force_unpin on error) → Task 5 step 6.
  - Testing — distributed across all tasks (TDD).
  - File map — matches the spec's file map exactly.
- **Placeholder scan:** every step has concrete code blocks or commands. No "TODO" / "TBD" / "implement appropriately."
- **Type/symbol consistency:** `FileNavigatorWidget`, `NavMode`, `NavMode.LIST`, `NavMode.PILL`, `_file_navigator`, `_pin_slot`, `_flow_slot`, `_scroll_area`, `_scroll_content`, `_diff_container`, `_diff_layout`, `_diff_model`, `_loader`, `_sticky_controller`, `_StickyPinController`, `set_active_file`, `set_mode`, `selection_model`, `currentChanged`, `deselected`, `force_unpin`, `recompute_threshold`, `on_owner_resize`, `HYSTERESIS_PX`, `_find_active_file_block` — all spelled identically across tasks.
- **Cross-task assumptions:** Task 4 leaves the navigator permanently in `_flow_slot` / LIST (no sticky behavior yet); Task 5 adds the controller and reparenting; Task 6 plugs auto-highlight into `_on_scroll`; Task 7 changes the scroll-reset behavior in render helpers. Each commit leaves the app in a working, testable state.
