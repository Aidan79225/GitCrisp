# MD3 Theming Batch 2 Design — Diff Live Refresh + Appearance Menu

**Date:** 2026-04-07
**Status:** Draft for review
**Parent docs:**
- `2026-04-07-md3-theming-design.md` (original)
- `2026-04-07-md3-theming-followups.md` (backlog)
- `2026-04-07-md3-theming-followups-batch1-design.md` (Batch 1)

## Goal

Two small, related improvements:

1. **Diff text live refresh.** Make the colored text inside an already-rendered diff (`+`/`-` lines, hunk header text, half-transparent backgrounds) update when the user switches theme — no need to close and re-open the file.
2. **Appearance menu.** Add a `View → Appearance` submenu to the main window's menu bar with three exclusive items (System / Light / Dark) so users can switch theme from the GUI.

## Non-Goals

- Settings dialog (deferred until user-defined themes work needs one).
- User-defined themes auto-discovery.
- Re-introducing a global QSS template.
- Any other menu items in `View` or anywhere else — only `Appearance` ships in this batch.

## 1. Diff text live refresh

### Current behavior

`make_file_block()` in `git_gui/presentation/widgets/diff_block.py`:
1. Builds a `QFrame` with `QPlainTextEdit` inside.
2. Calls `make_diff_formats()` to get a `DiffFormats` dataclass of baked `QTextCharFormat` / `QTextBlockFormat` objects.
3. Iterates the file's hunks, calling `render_hunk_*` which uses cursor inserts to write text *with the formats baked in*.
4. Calls `connect_widget(frame, rebuild=_rebuild)` where `_rebuild` re-applies the frame and header label stylesheets.

Problem: `_rebuild` does NOT re-render the diff text, so the `+`/`-` foreground colors and overlay backgrounds remain at whatever they were when the file was first opened.

### New behavior

`make_file_block()` will:
1. Capture the source `hunks` and rendering helper closure on local variables that the `_rebuild` closure can reference.
2. Provide a `_rerender()` inner function that:
   - Clears the QPlainTextEdit's contents (`text_edit.clear()`).
   - Calls `make_diff_formats()` again to get fresh format objects (which read from the current theme).
   - Re-runs the same hunk rendering logic.
3. `_rebuild` calls `_rerender()` in addition to the existing stylesheet refresh.

### Implementation outline

```python
def make_file_block(file_path, hunks, ...) -> tuple[QFrame, ...]:
    # ... existing setup of frame, header_label, text_edit ...

    def _render():
        text_edit.clear()
        formats = make_diff_formats()
        cursor = text_edit.textCursor()
        for hunk in hunks:
            render_hunk_header(cursor, hunk, formats)
            for line in hunk.lines:
                render_hunk_line(cursor, line, formats)

    _render()  # initial render

    def _rebuild():
        frame.setStyleSheet(_file_block_style())
        header_label.setStyleSheet(_header_style())
        _render()  # re-render diff text with fresh formats

    connect_widget(frame, rebuild=_rebuild)
    return frame, ...
```

The exact structure of the existing `render_hunk_*` calls determines the body of `_render`. The migration extracts whatever rendering logic is currently inline in `make_file_block` into the new `_render` closure.

### Edge cases

- **Scroll position.** Re-rendering wipes the text edit, which loses the user's scroll position. Save and restore: `pos = text_edit.verticalScrollBar().value()` before, restore after.
- **Selection.** Selections get wiped — acceptable for a theme switch (rare event).
- **Cursor position.** Same as selection — acceptable to lose.
- **Performance.** Re-rendering a large file's diff on every theme change is fine (theme change is rare and explicit).

### Testing

The existing `test_diff_block_refreshes_on_theme_change` smoke test asserts `update()` was called. Extend it: after the second `set_mode`, assert that `text_edit.toPlainText()` is non-empty (proving the rerender ran without crashing). This is a regression test, not a visual one.

## 2. Appearance menu

### UX

```
[ menu bar ]
View
  └── Appearance
        ├── ● System    (checkmark = current)
        ├── ○ Light
        └── ○ Dark
```

- Three `QAction` items in a `QActionGroup` (`setExclusive(True)`).
- Each action `setCheckable(True)`.
- `triggered` connects to a slot that calls `ThemeManager.set_mode(...)`.
- The currently-active mode's action is checked on construction and re-checked when `theme_changed` fires (so `colorSchemeChanged` from macOS appearance also flips the checkmark in System mode).

### Code location

A new helper module `git_gui/presentation/menus/appearance.py` exposes:

```python
def install_appearance_menu(window: QMainWindow) -> None:
    """Add a `View → Appearance` submenu to `window`'s menu bar.

    Creates the View menu if it doesn't exist. Wires the three actions
    to ThemeManager and keeps the checkmark in sync with theme_changed.
    """
```

`MainWindow.__init__` calls `install_appearance_menu(self)` after the window is constructed.

### Why a separate module

- `MainWindow.__init__` is already 50+ lines. Adding ~30 lines of menu code makes it harder to read.
- The next batch will add more menu items (Settings dialog → preferences). Having `presentation/menus/` ready as a home is cheap and consistent.
- Easy to unit-test in isolation.

### Implementation outline

```python
# git_gui/presentation/menus/appearance.py
from __future__ import annotations
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMainWindow

from git_gui.presentation.theme import get_theme_manager


_MODE_LABELS = [
    ("system", "System"),
    ("light",  "Light"),
    ("dark",   "Dark"),
]


def install_appearance_menu(window: QMainWindow) -> None:
    bar = window.menuBar()
    view_menu = bar.addMenu("&View")
    appearance = view_menu.addMenu("&Appearance")

    group = QActionGroup(window)
    group.setExclusive(True)

    actions: dict[str, QAction] = {}
    mgr = get_theme_manager()
    for mode, label in _MODE_LABELS:
        action = QAction(label, window)
        action.setCheckable(True)
        action.setChecked(mgr.mode == mode)
        action.triggered.connect(lambda _checked=False, m=mode: mgr.set_mode(m))
        group.addAction(action)
        appearance.addAction(action)
        actions[mode] = action

    def _on_theme_changed(_theme):
        # ThemeManager.mode reflects the user-chosen mode (system/light/dark),
        # not the resolved theme. The checkmark follows the user choice.
        current = mgr.mode
        if current in actions:
            actions[current].setChecked(True)

    mgr.theme_changed.connect(_on_theme_changed)
    # Hold a reference so the slot isn't GC'd.
    window._appearance_actions = actions  # type: ignore[attr-defined]
```

Note on the `_on_theme_changed` slot: in **System** mode, when macOS flips appearance, `theme_changed` fires but `mgr.mode` is still `"system"` — so the System action stays checked. Correct behavior.

### Edge cases

- **No menu bar exists today.** `QMainWindow.menuBar()` lazily creates one — calling it adds the bar to the window. No setup needed.
- **macOS native menu bar.** On macOS, Qt by default puts the menu bar in the system menu bar (top of screen) when the menu items match certain heuristics. "View → Appearance" doesn't trigger any special heuristic, so it appears as a regular app menu. Acceptable.
- **Menu mnemonic conflicts.** `&View` uses Alt+V, `&Appearance` uses A. No conflicts with anything else (since this is the only menu).

### Testing

`tests/presentation/menus/test_appearance.py`:

- After `install_appearance_menu(window)`, the menu bar contains `View → Appearance` with three actions.
- Triggering each action calls `ThemeManager.set_mode` with the right mode.
- Initial checkmark matches `ThemeManager.mode`.
- After `set_mode("light")`, the Light action is checked and the others are not.

Use `qtbot` for the QMainWindow fixture; trigger actions via `action.trigger()`.

## 3. File structure

**New:**
- `git_gui/presentation/menus/__init__.py`
- `git_gui/presentation/menus/appearance.py`
- `tests/presentation/menus/__init__.py`
- `tests/presentation/menus/test_appearance.py`

**Modified:**
- `git_gui/presentation/widgets/diff_block.py` — extract rendering into `_render`, call from `_rebuild`. Save/restore scroll position.
- `git_gui/presentation/main_window.py` — call `install_appearance_menu(self)` in `__init__`.
- `tests/presentation/widgets/test_theme_live_switching.py` — extend `test_diff_block_refreshes_on_theme_change` with the rerender assertion.

## 4. Risks

- **Diff rerender perf on huge files.** A diff of a 5000-line file might take ~100ms to rerender. Theme switching is rare and explicit, so acceptable. If profiling shows it's a problem we'll optimize later.
- **Scroll position drift.** Restoring `verticalScrollBar().value()` after a `clear()` and re-fill may not be perfect (the scroll bar's range is recalculated). Worst case the user sees the diff jump to a nearby line. Acceptable for a theme switch.
- **Menu bar appearing on macOS unexpectedly.** Some users may not have noticed the app had no menu bar before. Adding one is a visible change but a positive one (more discoverable).

## 5. Success criteria

- Switching theme via the new menu while a diff is open shows the new colors immediately, without closing the file.
- The menu bar shows `View → Appearance` with three radio items, the current mode checked.
- Triggering an item switches the theme live and persists to settings.
- All tests pass, including the new menu and rerender tests.
