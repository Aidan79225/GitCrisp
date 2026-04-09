# MD3 Theming Followups — Batch 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tokenize all remaining hardcoded colors in the widgets layer and make `ThemeManager.set_mode()` update the running app live (no restart).

**Architecture:** (1) Add 13 new color tokens to the `Theme` dataclass and both builtin JSON files; replace every `# TODO(theme)` literal with a token read via the existing lazy-getter pattern. (2) Add a `connect_widget(widget, rebuild=None)` helper that wires `ThemeManager.theme_changed` to the widget's `update()` (and an optional rebuild callback for stylesheet-cached widgets). Each migrated widget calls `connect_widget` once in its constructor.

**Tech Stack:** Python 3.13, PySide6 (Qt 6), `uv run` for all Python execution, pytest, pytest-qt.

**Spec:** `docs/superpowers/specs/2026-04-07-md3-theming-followups-batch1-design.md`

---

## File Structure

**New:**
- `git_gui/presentation/theme/live.py` — `connect_widget` helper.
- `tests/presentation/theme/test_tokens_extended.py`
- `tests/presentation/widgets/__init__.py` (if missing)
- `tests/presentation/widgets/test_theme_live_switching.py`

**Modified:**
- `git_gui/presentation/theme/tokens.py` — 13 new fields on `Colors`, plus `status_color()` helper.
- `git_gui/presentation/theme/builtin/light.json`
- `git_gui/presentation/theme/builtin/dark.json`
- `git_gui/presentation/theme/__init__.py` — re-export `connect_widget`.
- `git_gui/presentation/widgets/working_tree.py`
- `git_gui/presentation/widgets/diff.py`
- `git_gui/presentation/widgets/commit_info_delegate.py`
- `git_gui/presentation/widgets/ref_badge_delegate.py`
- `git_gui/presentation/widgets/insight_dialog.py`
- `git_gui/presentation/widgets/diff_block.py`
- `git_gui/presentation/widgets/commit_detail.py`
- `git_gui/presentation/widgets/graph.py`
- `git_gui/presentation/widgets/sidebar.py`
- `git_gui/presentation/widgets/repo_list.py`
- `git_gui/presentation/widgets/clone_dialog.py`
- `git_gui/presentation/widgets/log_panel.py`

---

## Conventions

- All Python execution via `uv run` (per `CLAUDE.md`).
- Tests: `uv run pytest tests/ -q` for the full suite, `-v` for individual files.
- Commits are small and frequent. Each task ends with one commit unless noted.
- **Do not change padding, sizes, fonts, layout, or visual appearance.** All token defaults exactly mirror the literals they replace.
- Use lazy getters for module-level constants (do **not** call `get_theme_manager()` at import time — the manager doesn't exist yet during module import; it's set up in `main.py`).

---

## Task 1: Add 13 new color tokens to the `Colors` dataclass

**Files:**
- Modify: `git_gui/presentation/theme/tokens.py`
- Test: `tests/presentation/theme/test_tokens_extended.py`

- [ ] **Step 1: Write the failing test**

Create `tests/presentation/theme/test_tokens_extended.py`:

```python
from git_gui.presentation.theme.tokens import Colors
from PySide6.QtGui import QColor


_NEW_TOKEN_NAMES = [
    "status_modified", "status_added", "status_deleted",
    "status_renamed", "status_unknown",
    "branch_head_bg",
    "diff_file_header_fg", "diff_hunk_header_fg",
    "diff_added_overlay", "diff_removed_overlay",
    "on_badge", "hover_overlay",
]


def _make_colors(**overrides):
    base = dict(
        primary="#264f78", on_primary="#ffffff",
        primary_container="#264f78", on_primary_container="#ffffff",
        secondary="#0d6efd", on_secondary="#ffffff",
        error="#f85149", on_error="#ffffff",
        surface="#252526", on_surface="#cccccc",
        surface_variant="#2a2d2e", on_surface_variant="#8b949e",
        surface_container="#1e1e1e", surface_container_high="#161b22",
        outline="#30363d", outline_variant="#30363d",
        background="#1e1e1e", on_background="#cccccc",
        diff_added_bg="#1d3a26", diff_added_fg="#ffffff",
        diff_removed_bg="#3e2025", diff_removed_fg="#ffffff",
        graph_lane_colors=["#4fc1ff"],
        ref_badge_branch_bg="#0d6efd",
        ref_badge_tag_bg="#a371f7",
        ref_badge_remote_bg="#1f4287",
        # New tokens
        status_modified="#1f6feb",
        status_added="#238636",
        status_deleted="#da3633",
        status_renamed="#f0883e",
        status_unknown="#8b949e",
        branch_head_bg="#238636",
        diff_file_header_fg="#e3b341",
        diff_hunk_header_fg="#58a6ff",
        diff_added_overlay="#23863650",
        diff_removed_overlay="#f8514950",
        on_badge="#ffffff",
        hover_overlay="#ffffff1e",
    )
    base.update(overrides)
    return Colors(**base)


def test_all_new_tokens_exist():
    c = _make_colors()
    for name in _NEW_TOKEN_NAMES:
        assert hasattr(c, name), f"missing token {name}"


def test_status_color_lookup():
    c = _make_colors()
    assert c.status_color("modified").name() == "#1f6feb"
    assert c.status_color("added").name() == "#238636"
    assert c.status_color("deleted").name() == "#da3633"
    assert c.status_color("renamed").name() == "#f0883e"
    assert c.status_color("unknown").name() == "#8b949e"


def test_status_color_falls_back_to_unknown():
    c = _make_colors()
    assert c.status_color("nonexistent").name() == c.status_color("unknown").name()


def test_overlay_tokens_carry_alpha():
    c = _make_colors()
    qc = c.as_qcolor("diff_added_overlay")
    assert isinstance(qc, QColor)
    assert qc.alpha() < 255
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/presentation/theme/test_tokens_extended.py -v`
Expected: FAIL — `Colors.__init__()` rejects the new keyword arguments (`unexpected keyword argument 'status_modified'`).

- [ ] **Step 3: Add the 13 new fields and helper to `Colors`**

Open `git_gui/presentation/theme/tokens.py`. Inside the existing `@dataclass(frozen=True)\nclass Colors:` block, after the existing `ref_badge_remote_bg: str` field, add:

```python
    # Status colors (working tree / diff badges)
    status_modified: str
    status_added: str
    status_deleted: str
    status_renamed: str
    status_unknown: str
    # Branch
    branch_head_bg: str
    # Diff accents
    diff_file_header_fg: str
    diff_hunk_header_fg: str
    diff_added_overlay: str
    diff_removed_overlay: str
    # Misc
    on_badge: str
    hover_overlay: str
```

Then, inside the `Colors` class body (after `as_qcolor`), add the helper method:

```python
    def status_color(self, kind: str) -> QColor:
        """Return the badge color for a working-tree delta kind.

        Falls back to status_unknown if the kind is not recognized.
        """
        name = f"status_{kind}"
        if hasattr(self, name):
            return self.as_qcolor(name)
        return self.as_qcolor("status_unknown")
```

- [ ] **Step 4: Run the new test**

Run: `uv run pytest tests/presentation/theme/test_tokens_extended.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Run the full theme test suite to confirm nothing else broke**

Run: `uv run pytest tests/presentation/theme/ -v`
Expected: existing token/loader tests will FAIL because `light.json` / `dark.json` are now missing the new required keys. That's expected — Task 2 fixes them.

- [ ] **Step 6: Commit**

```bash
git add git_gui/presentation/theme/tokens.py tests/presentation/theme/test_tokens_extended.py
git commit -m "feat(theme): add 13 new color tokens and status_color helper"
```

---

## Task 2: Add the 13 token values to both builtin JSON files

**Files:**
- Modify: `git_gui/presentation/theme/builtin/light.json`
- Modify: `git_gui/presentation/theme/builtin/dark.json`

- [ ] **Step 1: Add new keys to `dark.json`**

Open `git_gui/presentation/theme/builtin/dark.json`. Inside `"colors": { ... }`, after `"ref_badge_remote_bg": "#1f4287"`, add a comma and these 12 keys (note: the JSON spec table in the design has 12 unique tokens since `status_*` is 5 entries):

```json
    "status_modified": "#1f6feb",
    "status_added": "#238636",
    "status_deleted": "#da3633",
    "status_renamed": "#f0883e",
    "status_unknown": "#8b949e",
    "branch_head_bg": "#238636",
    "diff_file_header_fg": "#e3b341",
    "diff_hunk_header_fg": "#58a6ff",
    "diff_added_overlay": "#23863650",
    "diff_removed_overlay": "#f8514950",
    "on_badge": "#ffffff",
    "hover_overlay": "#ffffff1e"
```

Make sure the previous line (`"ref_badge_remote_bg"`) ends with a comma now, and the last new line (`"hover_overlay"`) does **not** have a trailing comma — it's the last entry in the `"colors"` object.

- [ ] **Step 2: Add new keys to `light.json`**

Open `git_gui/presentation/theme/builtin/light.json`. Same procedure, with these light-mode values:

```json
    "status_modified": "#1f6feb",
    "status_added": "#238636",
    "status_deleted": "#da3633",
    "status_renamed": "#f0883e",
    "status_unknown": "#8b949e",
    "branch_head_bg": "#238636",
    "diff_file_header_fg": "#9a6700",
    "diff_hunk_header_fg": "#0969da",
    "diff_added_overlay": "#23863650",
    "diff_removed_overlay": "#f8514950",
    "on_badge": "#ffffff",
    "hover_overlay": "#0000001e"
```

- [ ] **Step 3: Run the full theme test suite**

Run: `uv run pytest tests/presentation/theme/ -v`
Expected: ALL PASS (loader tests and the new tokens-extended tests).

- [ ] **Step 4: Run the entire test suite**

Run: `uv run pytest tests/ -q`
Expected: ALL PASS (the existing 143 tests plus the 4 new ones — 147 total).

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/theme/builtin/light.json git_gui/presentation/theme/builtin/dark.json
git commit -m "feat(theme): add 13 new token values to builtin light and dark JSON"
```

---

## Task 3: Add `connect_widget` helper module

**Files:**
- Create: `git_gui/presentation/theme/live.py`
- Modify: `git_gui/presentation/theme/__init__.py`

- [ ] **Step 1: Create `live.py`**

Write to `git_gui/presentation/theme/live.py`:

```python
"""Live theme switching helpers.

`connect_widget` wires a widget to refresh on `ThemeManager.theme_changed`.
For widgets that built their stylesheet from f-strings (and cached the
result), pass `rebuild` so the stylesheet is rebuilt before update().

The slot is stored on the widget instance so PySide6 sees the ownership
relationship and auto-disconnects when the widget is destroyed.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtWidgets import QWidget

from .manager import get_theme_manager
from .tokens import Theme


def connect_widget(
    widget: QWidget,
    rebuild: Optional[Callable[[], None]] = None,
) -> None:
    """Refresh `widget` whenever the active theme changes.

    Args:
        widget: The widget to refresh. Its `update()` will be called.
        rebuild: Optional callable invoked before `update()` to rebuild
            cached stylesheet strings.
    """
    def _on_theme_changed(_theme: Theme) -> None:
        if rebuild is not None:
            rebuild()
        widget.update()

    # Store on the widget so the connection's lifetime is tied to it.
    widget._theme_slot = _on_theme_changed  # type: ignore[attr-defined]
    get_theme_manager().theme_changed.connect(widget._theme_slot)
```

- [ ] **Step 2: Re-export from package `__init__`**

Open `git_gui/presentation/theme/__init__.py`. After the existing `from .manager import ...` line, add:

```python
from .live import connect_widget
```

And add `"connect_widget"` to the `__all__` list.

- [ ] **Step 3: Smoke import**

Run:
```bash
uv run python -c "from git_gui.presentation.theme import connect_widget; print('ok')"
```
Expected: `ok`.

- [ ] **Step 4: Run the full test suite**

Run: `uv run pytest tests/ -q`
Expected: ALL PASS (no new tests yet — Task 4 adds them).

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/theme/live.py git_gui/presentation/theme/__init__.py
git commit -m "feat(theme): add connect_widget live-switching helper"
```

---

## Task 4: Live-switching smoke test scaffold

**Files:**
- Create: `tests/presentation/widgets/__init__.py` (if missing)
- Create: `tests/presentation/widgets/test_theme_live_switching.py`

This task adds the test infrastructure but starts with a single widget (sidebar) that's already migrated. Subsequent tasks (5–10) extend this test as more widgets are wired up.

- [ ] **Step 1: Ensure tests/presentation/widgets package exists**

Check if `tests/presentation/widgets/__init__.py` exists. If not, create it as an empty file:

Run: `uv run python -c "from pathlib import Path; p=Path('tests/presentation/widgets/__init__.py'); p.parent.mkdir(parents=True, exist_ok=True); p.touch()"`

- [ ] **Step 2: Write the smoke test for sidebar**

Create `tests/presentation/widgets/test_theme_live_switching.py`:

```python
"""Smoke test: every theme-aware widget refreshes on theme_changed.

The test for each widget:
  1. Build the widget under a qtbot fixture.
  2. Spy on its update() method.
  3. Call get_theme_manager().set_mode("light") then set_mode("dark").
  4. Assert update() was called and the widget did not raise.

If a widget caches a stylesheet string in __init__, additionally spy
on _rebuild_styles to confirm the rebuild path runs.
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from git_gui.presentation.theme import get_theme_manager


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def reset_theme():
    """Reset the active theme to dark after each test."""
    yield
    get_theme_manager().set_mode("dark")


def _spy_update(widget) -> list[int]:
    """Replace widget.update with a counting wrapper. Returns the call list."""
    calls: list[int] = []
    original = widget.update

    def wrapped(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    widget.update = wrapped  # type: ignore[method-assign]
    return calls


def test_sidebar_refreshes_on_theme_change(app, reset_theme):
    from git_gui.presentation.widgets.sidebar import SidebarWidget

    widget = SidebarWidget(queries=None, commands=None)
    calls = _spy_update(widget)

    mgr = get_theme_manager()
    mgr.set_mode("light")
    mgr.set_mode("dark")

    assert len(calls) >= 2, "expected update() to be called at least twice"
```

- [ ] **Step 3: Run the new test (it should fail — sidebar isn't connected yet)**

Run: `uv run pytest tests/presentation/widgets/test_theme_live_switching.py -v`
Expected: FAIL — `update()` is not called because `SidebarWidget` does not yet call `connect_widget`.

If sidebar already errors during construction (because `queries=None`), update the test to pass minimal stubs as needed. Read `git_gui/presentation/widgets/sidebar.py:68-89` to see the constructor signature; if it requires non-None `queries`, build a `unittest.mock.MagicMock()` and pass that.

- [ ] **Step 4: Wire sidebar to `connect_widget`**

Open `git_gui/presentation/widgets/sidebar.py`. At the top, add to imports:

```python
from git_gui.presentation.theme import connect_widget
```

In `SidebarWidget.__init__`, after `layout.addWidget(self._tree)` (the last line of the existing constructor), add:

```python
        connect_widget(self)
```

- [ ] **Step 5: Run the test**

Run: `uv run pytest tests/presentation/widgets/test_theme_live_switching.py -v`
Expected: PASS.

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest tests/ -q`
Expected: ALL PASS.

- [ ] **Step 7: Commit**

```bash
git add tests/presentation/widgets/__init__.py tests/presentation/widgets/test_theme_live_switching.py git_gui/presentation/widgets/sidebar.py
git commit -m "feat(theme): wire sidebar to live theme switching + smoke test scaffold"
```

---

## Task 5: Migrate `working_tree.py` and `diff.py` (status colors + connect_widget)

**Files:**
- Modify: `git_gui/presentation/widgets/working_tree.py`
- Modify: `git_gui/presentation/widgets/diff.py`
- Modify: `tests/presentation/widgets/test_theme_live_switching.py`

These two files share the `_DELTA_BADGE` pattern. Migrate them together.

- [ ] **Step 1: Audit current TODO sites**

Run: `uv run python -c "import re; t=open('git_gui/presentation/widgets/working_tree.py').read(); [print(i+1, l) for i,l in enumerate(t.splitlines()) if 'TODO(theme)' in l or '_DELTA_BADGE' in l]"`

And the same for `diff.py`. Note the line numbers and the surrounding code.

- [ ] **Step 2: Migrate `working_tree.py`**

Open `git_gui/presentation/widgets/working_tree.py`. The existing `_DELTA_BADGE` dict currently looks like:

```python
_DELTA_BADGE = {
    "modified": ("M", "#1f6feb"),
    "added":    ("A", "#238636"),
    ...
}
```

Replace it with a pure label map, since color now comes from the theme:

```python
# (label, kind) — color is read from theme.colors.status_color(kind) at paint time.
_DELTA_LABEL = {
    "modified": "M",
    "added":    "A",
    "deleted":  "D",
    "renamed":  "R",
    "unknown":  "?",
}
```

Find every site that read the color from `_DELTA_BADGE`. The migration agent already left TODO comments. For each painter-side site like:

```python
label, color = _DELTA_BADGE.get(delta, ("?", "#8b949e"))
...
painter.setBrush(QBrush(QColor(color)))
```

Replace with:

```python
label = _DELTA_LABEL.get(delta, "?")
painter.setBrush(QBrush(get_theme_manager().current.colors.status_color(delta)))
```

For the `painter.setPen(QColor("white"))` line for badge text (currently has `# TODO(theme)` next to it), replace with:

```python
painter.setPen(get_theme_manager().current.colors.as_qcolor("on_badge"))
```

Confirm `from git_gui.presentation.theme import get_theme_manager, connect_widget` is imported at the top (the first import was added by the prior migration; add `connect_widget` to the import list).

In the constructor of the main view widget in this file (the `QTreeView` subclass or its containing `QWidget`), add at the end of `__init__`:

```python
        connect_widget(self)
```

Read the file first to find the exact constructor. If there are multiple classes, the `connect_widget` call goes on the user-facing widget (the one created by `MainWindow`).

- [ ] **Step 3: Migrate `diff.py`**

Same pattern as Step 2 applied to `diff.py`. The `_DELTA_BADGE` dict, the `(label, color) = ...` site, the `QColor("white")` badge text site, and a `connect_widget(self)` call in the user-facing widget's `__init__`.

- [ ] **Step 4: Add tests for both widgets**

Open `tests/presentation/widgets/test_theme_live_switching.py`. After the existing `test_sidebar_refreshes_on_theme_change`, append:

```python
def test_working_tree_refreshes_on_theme_change(app, reset_theme):
    from unittest.mock import MagicMock
    from git_gui.presentation.widgets.working_tree import WorkingTreeWidget

    widget = WorkingTreeWidget(queries=MagicMock(), commands=MagicMock())
    calls = _spy_update(widget)

    mgr = get_theme_manager()
    mgr.set_mode("light")
    mgr.set_mode("dark")

    assert len(calls) >= 2


def test_diff_refreshes_on_theme_change(app, reset_theme):
    from unittest.mock import MagicMock
    from git_gui.presentation.widgets.diff import DiffWidget

    widget = DiffWidget(queries=MagicMock())
    calls = _spy_update(widget)

    mgr = get_theme_manager()
    mgr.set_mode("light")
    mgr.set_mode("dark")

    assert len(calls) >= 2
```

The exact class names (`WorkingTreeWidget`, `DiffWidget`) and constructor args may differ — Read each file first and adapt the test to the real signatures. Pass `MagicMock()` for any required dependencies.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/presentation/widgets/test_theme_live_switching.py -v`
Expected: 3 PASS (sidebar, working_tree, diff).

- [ ] **Step 6: Run full suite**

Run: `uv run pytest tests/ -q`
Expected: ALL PASS.

- [ ] **Step 7: Commit**

```bash
git add git_gui/presentation/widgets/working_tree.py git_gui/presentation/widgets/diff.py tests/presentation/widgets/test_theme_live_switching.py
git commit -m "refactor(widgets): tokenize status colors in working_tree and diff + live switching"
```

---

## Task 6: Migrate `commit_info_delegate.py` and `ref_badge_delegate.py`

**Files:**
- Modify: `git_gui/presentation/widgets/commit_info_delegate.py`
- Modify: `git_gui/presentation/widgets/ref_badge_delegate.py`

Delegates do not subscribe to `theme_changed` themselves. Their owning views do (via `connect_widget`), and `viewport().update()` triggers the delegate's `paint()` to re-fire and re-read from the theme.

- [ ] **Step 1: Migrate `commit_info_delegate.py`**

Find the three `QColor("white")` sites (currently with `# TODO(theme): ... text color` comments). Replace each with:

```python
painter.setPen(get_theme_manager().current.colors.as_qcolor("on_badge"))
```

Verify the file already imports `get_theme_manager`. Remove the TODO comments.

- [ ] **Step 2: Migrate `ref_badge_delegate.py`**

The file has `COLOR_HEAD = "#238636"` at module level with a TODO. Convert it to a lazy getter pattern alongside the existing `_color_local/_color_remote/_color_tag`:

```python
def _color_head() -> QColor:
    return get_theme_manager().current.colors.as_qcolor("branch_head_bg")
```

Find every site that uses `COLOR_HEAD` (probably `return QColor(COLOR_HEAD)` in two places) and replace with `return _color_head()`. Delete the `COLOR_HEAD` constant and its TODO comment.

The `painter.setPen(QColor("white"))` line for badge text → `painter.setPen(get_theme_manager().current.colors.as_qcolor("on_badge"))`. Remove its TODO comment.

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest tests/ -q`
Expected: ALL PASS. Existing badge color tests already initialize ThemeManager via `tests/conftest.py`.

- [ ] **Step 4: Commit**

```bash
git add git_gui/presentation/widgets/commit_info_delegate.py git_gui/presentation/widgets/ref_badge_delegate.py
git commit -m "refactor(widgets): tokenize HEAD and on_badge colors in delegates"
```

---

## Task 7: Migrate `diff_block.py` (file/hunk headers + diff overlays)

**Files:**
- Modify: `git_gui/presentation/widgets/diff_block.py`
- Modify: `tests/presentation/widgets/test_theme_live_switching.py`

`diff_block.py` is the most complex migration. It contains baked-in stylesheet strings, color literals in `QTextCharFormat` setup, and semi-transparent QColor literals.

- [ ] **Step 1: Read the current state**

Read `git_gui/presentation/widgets/diff_block.py` to see the existing structure (specifically the `HEADER_STYLE`, `HUNK_HEADER_COLOR`, `_file_block_style()`, `make_file_block`, and the `QTextCharFormat` setup).

- [ ] **Step 2: Convert the constants to lazy functions**

Replace:

```python
# TODO(theme): #e3b341 is a yellow accent ...
HEADER_STYLE = "color: #e3b341; font-weight: bold;"
# TODO(theme): #58a6ff is a domain blue accent ...
HUNK_HEADER_COLOR = "#58a6ff"
```

with:

```python
def _header_style() -> str:
    c = get_theme_manager().current.colors
    return f"color: {c.diff_file_header_fg}; font-weight: bold;"


def _hunk_header_color() -> str:
    return get_theme_manager().current.colors.diff_hunk_header_fg
```

- [ ] **Step 3: Replace HEADER_STYLE / HUNK_HEADER_COLOR usage sites**

Find every site that referenced the old constants. Common patterns and their replacements:

```python
header_label.setStyleSheet(HEADER_STYLE)
# becomes:
header_label.setStyleSheet(_header_style())
```

```python
fmt_header.setForeground(QColor(HUNK_HEADER_COLOR))
# becomes:
fmt_header.setForeground(QColor(_hunk_header_color()))
```

```python
header_label.setStyleSheet(f"color: {HUNK_HEADER_COLOR};")
# becomes:
header_label.setStyleSheet(f"color: {_hunk_header_color()};")
```

- [ ] **Step 4: Replace the semi-transparent backgrounds**

Find:

```python
blk_added.setBackground(QColor(35, 134, 54, 80))
blk_removed.setBackground(QColor(248, 81, 73, 80))
```

Replace with:

```python
c = get_theme_manager().current.colors
blk_added.setBackground(c.as_qcolor("diff_added_overlay"))
blk_removed.setBackground(c.as_qcolor("diff_removed_overlay"))
```

- [ ] **Step 5: Replace the `QColor("white")` foreground sites**

For `fmt_added`, `fmt_removed`, `fmt_default`: these are diff text on dark surface. Replace `QColor("white")` with `get_theme_manager().current.colors.as_qcolor("on_surface")`.

Remove all `# TODO(theme)` comments in this file.

- [ ] **Step 6: Verify no TODOs remain**

Run: `uv run python -c "t=open('git_gui/presentation/widgets/diff_block.py').read(); print('TODO count:', t.count('TODO(theme)'))"`
Expected: `TODO count: 0`.

- [ ] **Step 7: Wire `connect_widget` to the diff_block widget**

`diff_block.py` exports a `make_file_block` function that returns a `QFrame`, and may also export a `DiffBlockWidget` class. Read the file to find the user-facing widget.

If `make_file_block` returns a `QFrame`, the QFrame is the widget that needs `connect_widget`. Just before returning the frame, add:

```python
    def _rebuild():
        frame.setStyleSheet(_file_block_style())
        # If there's a header_label in scope, also re-apply _header_style():
        # header_label.setStyleSheet(_header_style())

    connect_widget(frame, rebuild=_rebuild)
    return frame
```

Adapt the closure to capture every `setStyleSheet` site that runs during `make_file_block`.

If there's also a class-based `DiffBlockWidget`, add `connect_widget(self, rebuild=self._rebuild_styles)` in its `__init__`, and extract its existing setStyleSheet calls into a `_rebuild_styles` method that gets called once at the end of `__init__`.

- [ ] **Step 8: Add live-switching test**

Append to `tests/presentation/widgets/test_theme_live_switching.py`:

```python
def test_diff_block_refreshes_on_theme_change(app, reset_theme):
    # make_file_block is the public factory; pass minimal args.
    from git_gui.presentation.widgets.diff_block import make_file_block

    # Build a frame with empty hunks; adapt args to the real signature.
    frame = make_file_block(file_path="example.py", hunks=[])
    calls = _spy_update(frame)

    mgr = get_theme_manager()
    mgr.set_mode("light")
    mgr.set_mode("dark")

    assert len(calls) >= 2
```

If `make_file_block` requires more arguments, Read the function signature and pass minimal stubs (empty lists, MagicMock).

- [ ] **Step 9: Run tests**

Run: `uv run pytest tests/presentation/widgets/test_theme_live_switching.py -v`
Expected: 4 PASS.

Run: `uv run pytest tests/ -q`
Expected: ALL PASS.

- [ ] **Step 10: Commit**

```bash
git add git_gui/presentation/widgets/diff_block.py tests/presentation/widgets/test_theme_live_switching.py
git commit -m "refactor(widgets): tokenize diff block colors and overlays + live switching"
```

---

## Task 8: Migrate `insight_dialog.py` (GREEN/RED constants + on_surface text)

**Files:**
- Modify: `git_gui/presentation/widgets/insight_dialog.py`
- Modify: `tests/presentation/widgets/test_theme_live_switching.py`

- [ ] **Step 1: Convert GREEN/RED to lazy getters**

Open `git_gui/presentation/widgets/insight_dialog.py`. Replace:

```python
GREEN = "#238636"          # additions  # TODO: theme token
RED = "#da3633"            # deletions  # TODO: theme token
```

with:

```python
def _green() -> str:
    return get_theme_manager().current.colors.status_added


def _red() -> str:
    return get_theme_manager().current.colors.status_deleted
```

- [ ] **Step 2: Replace usage sites**

Find every `QColor(GREEN)` / `QColor(RED)` site and replace with `QColor(_green())` / `QColor(_red())`. The painter calls become:

```python
painter.setPen(QColor(_green()))
painter.setBrush(QColor(_red()))
```

etc.

- [ ] **Step 3: Replace remaining `QColor("white")` sites**

Two title-label sites currently have `# TODO: theme token`. These are non-badge text, so use `on_surface`:

```python
painter.setPen(QColor("white"))  # TODO: theme token
# becomes:
painter.setPen(get_theme_manager().current.colors.as_qcolor("on_surface"))
```

For the `setStyleSheet("color: white; border: none;")` site:

```python
title_label.setStyleSheet(f"color: {get_theme_manager().current.colors.on_surface}; border: none;")
```

- [ ] **Step 4: Wire `connect_widget`**

In `InsightDialog.__init__`, after the existing layout setup, extract the existing setStyleSheet calls into a `_rebuild_styles(self)` method (if it doesn't already exist) and add at the end of `__init__`:

```python
        self._rebuild_styles()
        connect_widget(self, rebuild=self._rebuild_styles)
```

- [ ] **Step 5: Verify no TODOs**

Run: `uv run python -c "t=open('git_gui/presentation/widgets/insight_dialog.py').read(); print('TODO count:', t.count('TODO'))"`
Expected: `TODO count: 0`.

- [ ] **Step 6: Add live-switching test**

Append to the test file:

```python
def test_insight_dialog_refreshes_on_theme_change(app, reset_theme):
    from unittest.mock import MagicMock
    from git_gui.presentation.widgets.insight_dialog import InsightDialog

    dialog = InsightDialog(queries=MagicMock())
    calls = _spy_update(dialog)

    mgr = get_theme_manager()
    mgr.set_mode("light")
    mgr.set_mode("dark")

    assert len(calls) >= 2
```

Adapt the constructor args to match the real signature.

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/ -q`
Expected: ALL PASS.

- [ ] **Step 8: Commit**

```bash
git add git_gui/presentation/widgets/insight_dialog.py tests/presentation/widgets/test_theme_live_switching.py
git commit -m "refactor(widgets): tokenize insight dialog colors + live switching"
```

---

## Task 9: Migrate `commit_detail.py`, `graph.py`, `repo_list.py`, `clone_dialog.py`, `log_panel.py`

**Files:**
- Modify: `git_gui/presentation/widgets/commit_detail.py`
- Modify: `git_gui/presentation/widgets/graph.py`
- Modify: `git_gui/presentation/widgets/repo_list.py`
- Modify: `git_gui/presentation/widgets/clone_dialog.py`
- Modify: `git_gui/presentation/widgets/log_panel.py`
- Modify: `tests/presentation/widgets/test_theme_live_switching.py`

These files have either no remaining TODOs or only minor ones. Wire each up with `connect_widget` and clean up any leftover literals.

- [ ] **Step 1: `commit_detail.py`**

Replace the four `QColor("white")` sites with `get_theme_manager().current.colors.as_qcolor("on_surface")`. Add `connect_widget(self)` in the user-facing widget's `__init__`. Add `connect_widget` to the existing theme import.

- [ ] **Step 2: `graph.py`**

The file has `_BTN_STYLE` containing `rgba(255, 255, 255, 30)`. Convert to a lazy function:

```python
def _btn_style() -> str:
    return (
        "QPushButton { background: transparent; border: none; color: white; }"
        f"QPushButton:hover {{ background-color: {get_theme_manager().current.colors.hover_overlay}; }}"
    )
```

(Adapt the static parts of the original `_BTN_STYLE` — preserve everything that wasn't a color.)

Replace `setStyleSheet(_BTN_STYLE)` calls with `setStyleSheet(_btn_style())`. Add `connect_widget(self, rebuild=self._rebuild_styles)` in the constructor of the user-facing graph widget, and put the button setStyleSheet calls into a `_rebuild_styles` method called once at the end of `__init__`.

Remove the TODO comment.

- [ ] **Step 3: `repo_list.py`**

Add `connect_widget(self)` in the user-facing widget's `__init__`. Add `connect_widget` to the existing theme import. No literal cleanup needed.

- [ ] **Step 4: `clone_dialog.py`**

The existing `setStyleSheet(f"color: {c.error};")` is already theme-aware. Wrap the styling in a `_rebuild_styles` method called once at the end of `__init__`, then `connect_widget(self, rebuild=self._rebuild_styles)`.

- [ ] **Step 5: `log_panel.py`**

The existing `self._header.setStyleSheet(...)` already reads from the theme via f-string. Wrap it in a `_rebuild_styles` method called once at the end of `__init__`, then `connect_widget(self, rebuild=self._rebuild_styles)`.

- [ ] **Step 6: Add live-switching tests for each**

Append to `tests/presentation/widgets/test_theme_live_switching.py`:

```python
def test_commit_detail_refreshes(app, reset_theme):
    from unittest.mock import MagicMock
    from git_gui.presentation.widgets.commit_detail import CommitDetailWidget
    widget = CommitDetailWidget(queries=MagicMock())
    calls = _spy_update(widget)
    mgr = get_theme_manager()
    mgr.set_mode("light"); mgr.set_mode("dark")
    assert len(calls) >= 2


def test_graph_refreshes(app, reset_theme):
    from unittest.mock import MagicMock
    from git_gui.presentation.widgets.graph import GraphWidget
    widget = GraphWidget(queries=MagicMock(), commands=MagicMock())
    calls = _spy_update(widget)
    mgr = get_theme_manager()
    mgr.set_mode("light"); mgr.set_mode("dark")
    assert len(calls) >= 2


def test_repo_list_refreshes(app, reset_theme):
    from unittest.mock import MagicMock
    from git_gui.presentation.widgets.repo_list import RepoListWidget
    widget = RepoListWidget(repo_store=MagicMock())
    calls = _spy_update(widget)
    mgr = get_theme_manager()
    mgr.set_mode("light"); mgr.set_mode("dark")
    assert len(calls) >= 2


def test_clone_dialog_refreshes(app, reset_theme):
    from unittest.mock import MagicMock
    from git_gui.presentation.widgets.clone_dialog import CloneDialog
    dialog = CloneDialog(commands=MagicMock())
    calls = _spy_update(dialog)
    mgr = get_theme_manager()
    mgr.set_mode("light"); mgr.set_mode("dark")
    assert len(calls) >= 2


def test_log_panel_refreshes(app, reset_theme):
    from git_gui.presentation.widgets.log_panel import LogPanel
    panel = LogPanel()
    calls = _spy_update(panel)
    mgr = get_theme_manager()
    mgr.set_mode("light"); mgr.set_mode("dark")
    assert len(calls) >= 2
```

For each test, Read the corresponding widget file FIRST and adapt the import name and constructor signature to match what's actually there. Class names and arg lists may differ from the guesses above.

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/presentation/widgets/test_theme_live_switching.py -v`
Expected: all live-switching tests PASS.

Run: `uv run pytest tests/ -q`
Expected: ALL PASS.

- [ ] **Step 8: Commit**

```bash
git add git_gui/presentation/widgets/commit_detail.py git_gui/presentation/widgets/graph.py git_gui/presentation/widgets/repo_list.py git_gui/presentation/widgets/clone_dialog.py git_gui/presentation/widgets/log_panel.py tests/presentation/widgets/test_theme_live_switching.py
git commit -m "refactor(widgets): wire remaining widgets to live theme switching"
```

---

## Task 10: Final audit + manual smoke

- [ ] **Step 1: Grep for any remaining TODO(theme)**

Run:
```bash
uv run python -c "
import os, re
root='git_gui/presentation/widgets'
hits=[]
for f in sorted(os.listdir(root)):
    if not f.endswith('.py'): continue
    p=os.path.join(root,f)
    for i,l in enumerate(open(p,encoding='utf-8').read().splitlines()):
        if 'TODO(theme)' in l or 'TODO: theme' in l:
            hits.append((p,i+1,l.strip()))
for h in hits: print(h)
print('TOTAL:', len(hits))
"
```
Expected: `TOTAL: 0`. If any remain, fix them.

- [ ] **Step 2: Grep for hardcoded hex literals or QColor("white")**

Run:
```bash
uv run python -c "
import os, re
root='git_gui/presentation/widgets'
pat=re.compile(r'#[0-9a-fA-F]{6}|QColor\(\"white\"\)')
for f in sorted(os.listdir(root)):
    if not f.endswith('.py'): continue
    p=os.path.join(root,f)
    for i,l in enumerate(open(p,encoding='utf-8').read().splitlines()):
        if pat.search(l):
            print(f'{p}:{i+1}: {l.rstrip()}')
"
```

Expected: every match is either inside an f-string referencing `c.<token>` or inside a comment. No bare hex or `QColor("white")` calls.

If anything legitimate remains (e.g. a fallback hex inside a getter, a static "transparent" string), leave it alone — but if there's an actual bare literal, fix it.

- [ ] **Step 3: Run the full test suite**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS, including all the live-switching tests.

- [ ] **Step 4: Manual smoke test**

Run: `uv run python main.py`

In a separate terminal, attach via `python` REPL is impractical for a Qt app — instead, edit `main.py` temporarily to call `theme_manager.set_mode("light")` after a 3-second `QTimer`, then revert. OR: build a tiny one-shot script:

```bash
uv run python -c "
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
sys.argv = ['test']
app = QApplication(sys.argv)
from git_gui.presentation.theme import ThemeManager, set_theme_manager
mgr = ThemeManager(app); set_theme_manager(mgr)
from git_gui.presentation.main_window import MainWindow
# Substitute a stub repo_path or skip if MainWindow needs one
print('mode:', mgr.mode)
mgr.set_mode('light'); print('switched to', mgr.mode)
mgr.set_mode('dark'); print('switched to', mgr.mode)
"
```
Expected: prints three modes, no exceptions.

(If launching `MainWindow` is required to fully verify visually, skip this step and rely on the smoke tests.)

- [ ] **Step 5: Commit any final fixes (if any)**

```bash
git status
# Only commit if there are pending changes from the audit
```

---

## Summary of Spec Coverage

| Spec section | Tasks |
|---|---|
| 13 new tokens on `Colors` | 1 |
| `status_color()` helper | 1 |
| Builtin JSON values | 2 |
| `connect_widget` helper | 3 |
| `theme/__init__.py` re-export | 3 |
| working_tree + diff status migration | 5 |
| commit_info / ref_badge delegate migration | 6 |
| diff_block migration | 7 |
| insight_dialog migration | 8 |
| commit_detail / graph / repo_list / clone_dialog / log_panel migration | 9 |
| Sidebar wiring (pilot) | 4 |
| Live-switching smoke tests | 4, 5, 7, 8, 9 |
| Token unit tests | 1 |
| Final audit | 10 |
