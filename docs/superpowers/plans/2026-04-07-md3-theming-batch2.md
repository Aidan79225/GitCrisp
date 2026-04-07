# MD3 Theming Batch 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix diff text live refresh limitation from Batch 1 and add a `View → Appearance` menu bar item for switching theme in the GUI.

**Architecture:** (1) `add_hunk_widget` attaches a per-hunk `connect_widget` rebuild closure that re-runs `render_hunk_content_lines` with fresh `DiffFormats` and re-applies the hunk header label's stylesheet, preserving scroll position. (2) A new `git_gui/presentation/menus/appearance.py` module exposes `install_appearance_menu(window)` which creates a `View → Appearance` submenu with three exclusive `QAction`s wired to `ThemeManager.set_mode`; `MainWindow.__init__` calls it once.

**Tech Stack:** Python 3.13, PySide6 (Qt 6), `uv run`, pytest, pytest-qt.

**Spec:** `docs/superpowers/specs/2026-04-07-md3-theming-batch2-design.md`

---

## File Structure

**New:**
- `git_gui/presentation/menus/__init__.py`
- `git_gui/presentation/menus/appearance.py`
- `tests/presentation/menus/__init__.py`
- `tests/presentation/menus/test_appearance.py`

**Modified:**
- `git_gui/presentation/widgets/diff_block.py` — `add_hunk_widget` gets a per-hunk rerender closure; `make_file_block`'s existing `_rebuild` stays as-is. The "known limitation" docstring in `make_diff_formats` is removed.
- `git_gui/presentation/main_window.py` — calls `install_appearance_menu(self)` in `__init__`.
- `tests/presentation/widgets/test_theme_live_switching.py` — extend existing `test_diff_block_refreshes_on_theme_change` to assert the text remains non-empty after a theme switch.
- `docs/superpowers/specs/2026-04-07-md3-theming-followups.md` — mark the diff live-refresh item as **resolved** in the "Known limitations" section.

## Architectural notes (important for the implementer)

Before editing, understand the existing diff rendering shape:

- `make_file_block(path)` returns an empty frame + inner QVBoxLayout. It does NOT contain any diff editor — it's just the outer card with the file header label.
- `add_hunk_widget(parent_layout, hunk, formats, ...)` is called multiple times (once per hunk). Each call appends:
  1. A header row `QWidget` containing a `QLabel` colored via `f"color: {_hunk_header_color()};"`
  2. A fresh `QPlainTextEdit` (from `make_diff_editor()`) whose cursor is filled by `render_hunk_content_lines(cursor, hunk, formats)`.
- Each hunk's editor is **fixed-height** (sized to its content) and has no scroll bars — so "preserve scroll position" doesn't apply per-editor.
- The file block's `connect_widget` rebuild closure already re-applies the frame style and file-header label style. What it's **missing** is refreshing each hunk's editor text and hunk-header label.

The fix lives inside `add_hunk_widget`: attach `connect_widget(editor, rebuild=_rerender_this_hunk)` to each hunk's editor. The `_rerender_this_hunk` closure captures `hunk`, `editor`, and `header_label`, calls `make_diff_formats()` fresh, clears the editor, re-runs `render_hunk_content_lines`, and re-applies `header_label.setStyleSheet(...)`.

---

## Conventions

- All Python execution via `uv run` (per `CLAUDE.md`).
- Tests: `uv run pytest tests/ -q`.
- Commits small and frequent; one per task unless noted.
- Do not change padding, layout, or visual appearance except where the spec explicitly calls for it.

---

## Task 1: Wire per-hunk rerender into `add_hunk_widget`

**Files:**
- Modify: `git_gui/presentation/widgets/diff_block.py`
- Modify: `tests/presentation/widgets/test_theme_live_switching.py`

- [ ] **Step 1: Read the existing `add_hunk_widget` and `render_hunk_content_lines`**

Run `Read` on `git_gui/presentation/widgets/diff_block.py` to refresh your memory of the exact structure. Key regions:
- `add_hunk_widget` lines ~219–272 — the function that needs the rerender closure.
- `render_hunk_content_lines` — used inside the rerender closure.
- `_hunk_header_color()` — used to rebuild the hunk header label stylesheet.

- [ ] **Step 2: Edit `add_hunk_widget` to add the rerender closure**

Replace the current body of `add_hunk_widget` (after setting `extra_left_widgets` / `extra_right_widgets` defaults) with this version. Key changes:
- Extract the initial render into a local `_render()` closure that can be called again.
- Define `_rebuild()` that rebuilds the header label stylesheet AND calls `_render()`.
- Call `connect_widget(editor, rebuild=_rebuild)` before returning.

Use this exact code for the function body (replacing everything from "# --- Header row ---" to "parent_layout.addWidget(editor)"):

```python
    # --- Header row ---
    header_row = QWidget()
    header_layout = QHBoxLayout(header_row)
    header_layout.setContentsMargins(0, HEADER_ROW_VPAD, 0, HEADER_ROW_VPAD)
    header_layout.setSpacing(4)
    for w in extra_left_widgets:
        header_layout.addWidget(w)
    header_label = QLabel(hunk.header.strip())
    header_label.setStyleSheet(f"color: {_hunk_header_color()};")
    header_layout.addWidget(header_label)
    header_layout.addStretch()
    for w in extra_right_widgets:
        header_layout.addWidget(w)
    header_row.setFixedHeight(HEADER_ROW_HEIGHT + HEADER_ROW_VPAD * 2)

    # --- Diff editor ---
    editor = make_diff_editor()

    def _render(current_formats: DiffFormats) -> int:
        editor.clear()
        cursor = editor.textCursor()
        count = render_hunk_content_lines(cursor, hunk, current_formats)
        editor.setTextCursor(cursor)
        return count

    line_count = _render(formats)

    line_height = editor.fontMetrics().lineSpacing()
    margins = editor.contentsMargins()
    doc_margin = editor.document().documentMargin() * 2
    total_height = int(line_count * line_height + doc_margin + margins.top() + margins.bottom() + 4)
    editor.setFixedHeight(max(total_height, 4))
    editor.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def _rebuild() -> None:
        header_label.setStyleSheet(f"color: {_hunk_header_color()};")
        _render(make_diff_formats())

    connect_widget(editor, rebuild=_rebuild)

    parent_layout.addWidget(header_row)
    parent_layout.addWidget(editor)
```

Note: `_render` takes `current_formats` as an arg (not a closure over `formats`) so the rebuild path can pass a freshly-built `DiffFormats`.

- [ ] **Step 3: Remove the stale "Known limitation" docstring**

Open `git_gui/presentation/widgets/diff_block.py`. Find `def make_diff_formats()` and remove the "Known limitation:" paragraph from its docstring. Keep only the one-line summary:

```python
def make_diff_formats() -> DiffFormats:
    """Return a DiffFormats dataclass with all QTextCharFormat / QTextBlockFormat objects."""
```

- [ ] **Step 4: Extend the existing live-switching test**

Open `tests/presentation/widgets/test_theme_live_switching.py`. Find `test_diff_block_refreshes_on_theme_change`. Read what it currently does.

The existing test exercises `make_file_block` which has no hunks. We need a test that exercises `add_hunk_widget` with a real `Hunk` so the rerender path runs.

Replace or augment the test with:

```python
def test_diff_block_hunk_rerenders_on_theme_change(app, reset_theme):
    from PySide6.QtWidgets import QVBoxLayout, QWidget
    from git_gui.domain.entities import Hunk
    from git_gui.presentation.widgets.diff_block import (
        add_hunk_widget, make_diff_formats, make_file_block,
    )

    # Build a minimal file block + one hunk.
    frame, inner = make_file_block("example.py")
    hunk = Hunk(
        header="@@ -1,2 +1,2 @@",
        lines=[
            ("-", "old line\n"),
            ("+", "new line\n"),
            (" ", "context\n"),
        ],
    )
    formats = make_diff_formats()
    add_hunk_widget(inner, hunk, formats)

    # Locate the editor we just added.
    from PySide6.QtWidgets import QPlainTextEdit
    editors = frame.findChildren(QPlainTextEdit)
    assert len(editors) == 1
    editor = editors[0]

    initial_text = editor.toPlainText()
    assert "old line" in initial_text
    assert "new line" in initial_text

    mgr = get_theme_manager()
    mgr.set_mode("light")
    mgr.set_mode("dark")

    # After theme flips, the editor should still contain the re-rendered diff.
    text_after = editor.toPlainText()
    assert "old line" in text_after
    assert "new line" in text_after
```

Before adding this test, run `uv run python -c "from git_gui.domain.entities import Hunk; import inspect; print(inspect.signature(Hunk))"` to confirm the `Hunk` constructor signature. If the signature differs (e.g. requires extra fields), adapt the test's `Hunk(...)` call accordingly.

- [ ] **Step 5: Run the new test**

Run: `uv run pytest tests/presentation/widgets/test_theme_live_switching.py::test_diff_block_hunk_rerenders_on_theme_change -v`
Expected: PASS.

If it fails because `Hunk` has required fields not shown above, read `git_gui/domain/entities.py`, fix the construction, and rerun.

- [ ] **Step 6: Run the full test suite**

Run: `uv run pytest tests/ -q`
Expected: ALL PASS.

- [ ] **Step 7: Manual sanity check (optional)**

Run: `uv run python main.py`, open a file diff, then in a Python REPL (or via temporarily adding a menu — wait, Task 2 does that) switch themes. Confirm the diff text/backgrounds update live.

For this task, it's OK to skip the manual check and rely on the test — Task 2 will make the manual check trivial via the menu.

- [ ] **Step 8: Commit**

```bash
git add git_gui/presentation/widgets/diff_block.py tests/presentation/widgets/test_theme_live_switching.py
git commit -m "fix(diff): rerender hunk editors on theme change"
```

---

## Task 2: Create the `menus` package and `appearance` module

**Files:**
- Create: `git_gui/presentation/menus/__init__.py`
- Create: `git_gui/presentation/menus/appearance.py`
- Create: `tests/presentation/menus/__init__.py`
- Create: `tests/presentation/menus/test_appearance.py`

- [ ] **Step 1: Create the package skeletons**

Write these files:

`git_gui/presentation/menus/__init__.py`:
```python
"""GitStack main-window menu bar construction."""
```

`tests/presentation/menus/__init__.py` — empty file.

- [ ] **Step 2: Write the failing test**

Create `tests/presentation/menus/test_appearance.py`:

```python
"""Tests for the View → Appearance menu installer."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QMainWindow

from git_gui.presentation.menus.appearance import install_appearance_menu
from git_gui.presentation.theme import get_theme_manager


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def reset_theme():
    yield
    get_theme_manager().set_mode("dark")


def _find_appearance_actions(window: QMainWindow) -> dict:
    """Return {mode_label: QAction} from the window's View → Appearance submenu."""
    bar = window.menuBar()
    view_menu = None
    for action in bar.actions():
        if action.text().replace("&", "") == "View":
            view_menu = action.menu()
            break
    assert view_menu is not None, "View menu not found"

    appearance_menu = None
    for action in view_menu.actions():
        if action.text().replace("&", "") == "Appearance":
            appearance_menu = action.menu()
            break
    assert appearance_menu is not None, "Appearance submenu not found"

    return {
        a.text().replace("&", ""): a
        for a in appearance_menu.actions()
    }


def test_install_creates_three_actions(app, reset_theme):
    window = QMainWindow()
    install_appearance_menu(window)

    actions = _find_appearance_actions(window)
    assert set(actions.keys()) == {"System", "Light", "Dark"}
    for a in actions.values():
        assert a.isCheckable()


def test_initial_check_matches_current_mode(app, reset_theme):
    mgr = get_theme_manager()
    mgr.set_mode("dark")

    window = QMainWindow()
    install_appearance_menu(window)
    actions = _find_appearance_actions(window)

    assert actions["Dark"].isChecked()
    assert not actions["Light"].isChecked()
    assert not actions["System"].isChecked()


def test_triggering_action_changes_theme(app, reset_theme):
    mgr = get_theme_manager()
    mgr.set_mode("dark")

    window = QMainWindow()
    install_appearance_menu(window)
    actions = _find_appearance_actions(window)

    actions["Light"].trigger()
    assert mgr.mode == "light"


def test_checkmark_updates_when_mode_changes_externally(app, reset_theme):
    mgr = get_theme_manager()
    mgr.set_mode("dark")

    window = QMainWindow()
    install_appearance_menu(window)
    actions = _find_appearance_actions(window)

    # Change mode without going through the menu — the menu checkmark
    # should follow via the theme_changed signal.
    mgr.set_mode("light")
    assert actions["Light"].isChecked()
    assert not actions["Dark"].isChecked()
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/presentation/menus/test_appearance.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'git_gui.presentation.menus.appearance'`.

- [ ] **Step 4: Implement `appearance.py`**

Create `git_gui/presentation/menus/appearance.py`:

```python
"""Install a `View → Appearance` submenu for switching the app theme."""
from __future__ import annotations

from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMainWindow

from git_gui.presentation.theme import get_theme_manager


_MODE_LABELS: list[tuple[str, str]] = [
    ("system", "System"),
    ("light",  "Light"),
    ("dark",   "Dark"),
]


def install_appearance_menu(window: QMainWindow) -> None:
    """Add a `View → Appearance` submenu to `window`'s menu bar.

    Creates the View menu on the window's QMenuBar. Each of the three
    mode actions (System / Light / Dark) is checkable and exclusive; the
    currently-active mode is checked on construction and re-checked when
    ThemeManager.theme_changed fires.
    """
    bar = window.menuBar()
    view_menu = bar.addMenu("&View")
    appearance = view_menu.addMenu("&Appearance")

    group = QActionGroup(window)
    group.setExclusive(True)

    mgr = get_theme_manager()
    actions: dict[str, QAction] = {}
    for mode, label in _MODE_LABELS:
        action = QAction(label, window)
        action.setCheckable(True)
        action.setChecked(mgr.mode == mode)
        action.triggered.connect(
            lambda _checked=False, m=mode: mgr.set_mode(m)
        )
        group.addAction(action)
        appearance.addAction(action)
        actions[mode] = action

    def _on_theme_changed(_theme) -> None:
        current = mgr.mode
        if current in actions:
            actions[current].setChecked(True)

    mgr.theme_changed.connect(_on_theme_changed)

    # Hold a reference so neither the actions dict nor the slot is GC'd.
    window._appearance_actions = actions  # type: ignore[attr-defined]
    window._appearance_on_theme_changed = _on_theme_changed  # type: ignore[attr-defined]
```

- [ ] **Step 5: Run the new test**

Run: `uv run pytest tests/presentation/menus/test_appearance.py -v`
Expected: 4 PASS.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest tests/ -q`
Expected: ALL PASS.

- [ ] **Step 7: Commit**

```bash
git add git_gui/presentation/menus/__init__.py git_gui/presentation/menus/appearance.py tests/presentation/menus/__init__.py tests/presentation/menus/test_appearance.py
git commit -m "feat(menus): add View -> Appearance submenu for theme switching"
```

---

## Task 3: Wire `install_appearance_menu` into `MainWindow`

**Files:**
- Modify: `git_gui/presentation/main_window.py`

- [ ] **Step 1: Add the import**

Open `git_gui/presentation/main_window.py`. After the existing imports from `git_gui.presentation.widgets...`, add:

```python
from git_gui.presentation.menus.appearance import install_appearance_menu
```

- [ ] **Step 2: Call the installer in `__init__`**

In `MainWindow.__init__`, find a sensible place to call `install_appearance_menu(self)`. The menu bar only needs to exist — it doesn't depend on any other state. A good location: immediately after `self.setWindowTitle(...)` and before the widget construction block.

Add the line:

```python
        install_appearance_menu(self)
```

- [ ] **Step 3: Smoke test — launch the app**

Run: `uv run python main.py`

Expected:
- Main window opens with a menu bar at the top containing "View".
- "View → Appearance" has System / Light / Dark items.
- The current mode is checked.
- Triggering "Light" switches the app to light theme live; the diff text (if a file is open) updates.
- Triggering "Dark" flips back.

Close the app when done.

- [ ] **Step 4: Run the test suite**

Run: `uv run pytest tests/ -q`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/main_window.py
git commit -m "feat(main): install View -> Appearance menu on main window"
```

---

## Task 4: Update followups docs

**Files:**
- Modify: `docs/superpowers/specs/2026-04-07-md3-theming-followups.md`

- [ ] **Step 1: Update the "Known limitations" section**

Open `docs/superpowers/specs/2026-04-07-md3-theming-followups.md`. Find the "Known limitations carried over from Batch 1" section. Mark the diff text live-refresh item as resolved:

Replace the existing section header and body with:

```markdown
## Known limitations carried over from Batch 1

### Diff text colors do not update on live theme switch — RESOLVED in Batch 2

**Status:** Fixed in Batch 2 (`feat/md3-theming-batch2`).

`add_hunk_widget` now attaches a per-hunk `connect_widget` rebuild closure
that re-runs `render_hunk_content_lines` with fresh `DiffFormats` and
re-applies the hunk header label stylesheet. Diff text and overlay
backgrounds now refresh live along with the rest of the app.
```

- [ ] **Step 2: Commit the doc update**

```bash
git add docs/superpowers/specs/2026-04-07-md3-theming-followups.md
git commit -m "docs: mark diff live-refresh limitation as resolved in batch 2"
```

---

## Task 5: Final audit

- [ ] **Step 1: Verify test suite**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS — including the new menu tests and the extended diff rerender test.

- [ ] **Step 2: Manual end-to-end check**

Run: `uv run python main.py`.

1. Open a repo that has uncommitted changes or a commit with a diff.
2. Navigate to a file that shows diff lines (with `+` / `-`).
3. Note the current appearance (colors of the diff text and overlays).
4. Click **View → Appearance → Light**. Observe: the entire app flips to light theme, **including the already-displayed diff** (white-ish backgrounds on the + / - overlays, dark text).
5. Click **View → Appearance → Dark**. Observe: flips back to dark, the diff text/overlays update again without closing the file.
6. Click **View → Appearance → System**. Observe: the app matches your macOS/Windows appearance preference.

If any of these fail — particularly step 4's diff update — the rerender closure isn't wired correctly; re-check Task 1.

- [ ] **Step 3: Commit any fix-ups (only if needed)**

Run `git status`. If clean, no commit needed.

---

## Summary of Spec Coverage

| Spec section | Tasks |
|---|---|
| Diff live refresh — `add_hunk_widget` rerender closure | 1 |
| Extended diff rerender test | 1 |
| Remove stale "known limitation" docstring | 1 |
| `menus/appearance.py` module | 2 |
| Appearance menu unit tests | 2 |
| `MainWindow` wiring | 3 |
| Followups doc update | 4 |
| Manual end-to-end verification | 5 |
