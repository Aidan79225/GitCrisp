# MD3 Theming Followups — Batch 1 Design

**Date:** 2026-04-07
**Status:** Draft for review
**Parent docs:**
- `2026-04-07-md3-theming-design.md` (original spec)
- `2026-04-07-md3-theming-followups.md` (followups backlog)

## Goal

Finish two items from the followups backlog:

1. **Tokenize remaining hardcoded colors.** After this lands, no widget under `git_gui/presentation/widgets/` contains any `# TODO(theme)` literal — all colors come from the `Theme`.
2. **Live theme switching.** Calling `ThemeManager.set_mode("light"|"dark")` updates the running app immediately, without a restart, including widgets that built their stylesheets from f-strings.

## Non-Goals

- Settings UI dialog for choosing theme.
- User-defined themes auto-discovery.
- Re-introducing a global QSS template.
- MD3 seed-color tonal palette generator.
- Changing any widget layout, padding, or font.

## 1. New Theme Tokens

Added to `Theme.colors` (the `Colors` frozen dataclass). All 13 are required by the strict JSON loader, so both `light.json` and `dark.json` must include them.

| Token | Light | Dark | Replaces |
|---|---|---|---|
| `status_modified` | `#1f6feb` | `#1f6feb` | `_DELTA_BADGE["modified"]` (working_tree, diff) |
| `status_added` | `#238636` | `#238636` | `_DELTA_BADGE["added"]`; `insight_dialog.GREEN` |
| `status_deleted` | `#da3633` | `#da3633` | `_DELTA_BADGE["deleted"]`; `insight_dialog.RED` |
| `status_renamed` | `#f0883e` | `#f0883e` | `_DELTA_BADGE["renamed"]` |
| `status_unknown` | `#8b949e` | `#8b949e` | `_DELTA_BADGE["unknown"]` fallback |
| `branch_head_bg` | `#238636` | `#238636` | `ref_badge_delegate.COLOR_HEAD` |
| `diff_file_header_fg` | `#9a6700` | `#e3b341` | `diff_block.HEADER_STYLE` color |
| `diff_hunk_header_fg` | `#0969da` | `#58a6ff` | `diff_block.HUNK_HEADER_COLOR` |
| `diff_added_overlay` | `#23863650` | `#23863650` | `QColor(35,134,54,80)` in `diff_block` |
| `diff_removed_overlay` | `#f8514950` | `#f8514950` | `QColor(248,81,73,80)` in `diff_block` |
| `on_badge` | `#ffffff` | `#ffffff` | All `QColor("white")` badge text |
| `hover_overlay` | `#0000001e` | `#ffffff1e` | `rgba(255,255,255,30)` in `graph._BTN_STYLE` |

Hex8 values (`#RRGGBBAA`) carry alpha and are already accepted by the loader's `_HEX_RE` regex; no loader change required. `as_qcolor` returns a `QColor` constructed from the hex string, which `QColor` parses including alpha.

A `_DELTA_BADGE` lookup helper is added near the existing `Colors` token getters:

```python
def status_color(self, kind: str) -> QColor:
    """Return the badge color for a working-tree delta kind."""
    name = f"status_{kind}"
    return self.as_qcolor(name) if hasattr(self, name) else self.as_qcolor("status_unknown")
```

## 2. Migration of remaining literals

Every `# TODO(theme)` comment is removed, replaced with a token read.

### Per-file changes

- **`working_tree.py` / `diff.py`** — `_DELTA_BADGE` dicts keep the (label, kind) shape but stop carrying a hex string. Color comes from `theme.colors.status_color(kind)` at paint time. The kind→color binding becomes the only source of truth.
- **`commit_info_delegate.py` / `ref_badge_delegate.py` / `working_tree.py` / `diff.py` / `insight_dialog.py` / `diff_block.py`** — all `QColor("white")` calls inside delegate `paint()` for *badge* text become `theme.colors.as_qcolor("on_badge")`.
- **`commit_detail.py` / `insight_dialog.py` title labels** — `QColor("white")` for *non-badge* text becomes `theme.colors.as_qcolor("on_surface")` (these sit on `surface`, not on a colored badge).
- **`ref_badge_delegate.py`** — `COLOR_HEAD` constant → `_color_head()` lazy getter → `branch_head_bg`. The TODO comment goes.
- **`diff_block.py`**:
  - `HEADER_STYLE` becomes `_header_style()` returning `f"color: {c.diff_file_header_fg}; font-weight: bold;"`.
  - `HUNK_HEADER_COLOR` becomes `_hunk_header_color()` returning `c.diff_hunk_header_fg`.
  - The two `QColor(35, 134, 54, 80)` / `QColor(248, 81, 73, 80)` literals become `c.as_qcolor("diff_added_overlay")` / `c.as_qcolor("diff_removed_overlay")`.
  - Existing `make_file_block` switches from baked constants to a `_rebuild_styles` callable on the returned QFrame so live switching can rerun it.
- **`insight_dialog.py`** — `GREEN`/`RED` module constants become lazy getters returning `status_added`/`status_deleted`. White title-label text becomes `on_surface`.
- **`graph.py`** — `_BTN_STYLE`'s `rgba(255,255,255,30)` becomes a function `_btn_style()` returning the f-string with `{c.hover_overlay}`. The button's `setStyleSheet(_BTN_STYLE)` becomes `setStyleSheet(_btn_style())`.

After this section, a grep for `#[0-9a-f]{6}` and `QColor("white")` over `git_gui/presentation/widgets/` should return only matches inside f-strings that read the theme.

## 3. Live theme switching

### New helper: `git_gui/presentation/theme/live.py`

```python
from typing import Callable, Optional
from PySide6.QtWidgets import QWidget
from .manager import get_theme_manager
from .tokens import Theme


def connect_widget(widget: QWidget, rebuild: Optional[Callable[[], None]] = None) -> None:
    """Refresh a widget when the theme changes.

    rebuild: optional callable invoked before update() to rebuild any
             cached stylesheet strings. Use it for widgets that called
             setStyleSheet() with a baked-in color string.

    The connection lifetime is bound to the widget — when the widget is
    destroyed, Qt automatically disconnects the slot.
    """
    def _on_theme_changed(_theme: Theme) -> None:
        if rebuild is not None:
            rebuild()
        widget.update()

    get_theme_manager().theme_changed.connect(_on_theme_changed)
```

### Per-widget wiring

Each migrated widget gains one or two lines in `__init__`:

- **Paint-only widgets** (`graph`, `repo_list`, `sidebar`, `working_tree`, `diff`, `commit_detail`):
  ```python
  from git_gui.presentation.theme.live import connect_widget
  ...
  connect_widget(self)
  ```
- **setStyleSheet widgets** (`clone_dialog`, `log_panel`, `insight_dialog`, `diff_block`):
  - Extract the existing `setStyleSheet` calls into a `_rebuild_styles()` method (already done in the existing migration for some; complete the rest).
  - Call `self._rebuild_styles()` once at the end of `__init__`.
  - Then `connect_widget(self, rebuild=self._rebuild_styles)`.
- **Delegates** (`commit_info_delegate`, `ref_badge_delegate`, `graph_lane_delegate`): delegates have no `update()` of their own. The owning view (sidebar's `_SidebarTree`, repo_list's view, working_tree view, etc.) is already connected via `connect_widget` — when the view's `update()` runs, the delegate's `paint()` re-fires and reads from the lazy getters. **Delegates need no signal wiring.** This is the reason we kept the lazy-getter pattern in the original migration.

### `ThemeManager` changes

None. The existing `theme_changed` signal already does the job. The fix is purely on the widget-subscriber side.

### Edge cases

- **Color strings cached at module import** (e.g. an `f"color: {c.error};"` evaluated once at module load): all such sites are converted to functions returning the f-string. Audit during migration with `grep -nP "f\".*\\{[^}]*\\.colors\\." -r git_gui/presentation/widgets/`.
- **Reentrancy**: `set_mode()` is single-threaded (Qt GUI thread). No locking needed.
- **Disconnect on widget destruction**: Qt's auto-disconnect handles this because we connect a function that captures `widget` in a closure — when the widget is gone, the closure is reachable but `widget.update()` on a dead C++ object would crash. Mitigation: use `Qt.QueuedConnection` so updates are deferred to the event loop, by which time deletion is observable; **or** connect using `widget` as the receiver context: `mgr.theme_changed.connect(_on_theme_changed, type=Qt.AutoConnection)` won't auto-disconnect, but binding via `widget.destroyed` is overkill. Simpler: store the slot on the widget (`widget._theme_slot = _on_theme_changed`) and connect using `mgr.theme_changed.connect(widget._theme_slot)` — Qt sees the bound method's owner and auto-disconnects on destruction.

Final implementation in `connect_widget`:

```python
def connect_widget(widget, rebuild=None):
    def _on_theme_changed(_theme):
        if rebuild is not None:
            rebuild()
        widget.update()
    # Store on the widget so PySide6 sees ownership and auto-disconnects.
    widget._theme_slot = _on_theme_changed
    get_theme_manager().theme_changed.connect(widget._theme_slot)
```

## 4. Testing

### Unit tests

`tests/presentation/theme/test_tokens_extended.py`:

- All 13 new token names exist as fields on `Colors`.
- `Colors.status_color("modified")` returns the same QColor as `as_qcolor("status_modified")`.
- `Colors.status_color("nonexistent")` falls back to `status_unknown`.
- Loader accepts hex8 strings (e.g. `#23863650`) without raising.
- Both `light.json` and `dark.json` parse and contain all 13 new keys.

### Live-switching smoke test

`tests/presentation/widgets/test_theme_live_switching.py`:

- For each migrated widget, build an instance under a `qtbot` fixture, register a spy on `update()`, call `get_theme_manager().set_mode("light")` then `set_mode("dark")`, assert the spy fired and the widget did not raise.
- For setStyleSheet widgets, additionally assert `_rebuild_styles` was invoked (spy on the method).
- This is the scariest regression — "I forgot to wire connect_widget" — and the simplest test to catch it.

No pixel comparisons; no qtbot screenshots.

## 5. File structure

**New:**
- `git_gui/presentation/theme/live.py` — `connect_widget` helper.
- `tests/presentation/theme/test_tokens_extended.py`
- `tests/presentation/widgets/test_theme_live_switching.py`

**Modified:**
- `git_gui/presentation/theme/tokens.py` — 13 new fields on `Colors`, `status_color` helper.
- `git_gui/presentation/theme/builtin/light.json` — 13 new color values.
- `git_gui/presentation/theme/builtin/dark.json` — 13 new color values.
- `git_gui/presentation/theme/__init__.py` — re-export `connect_widget`.
- All 13 widgets that have `# TODO(theme)` comments today.

## 6. Risks

- **Deferred slot crash on destroyed widget.** Mitigated by binding the slot to the widget instance so Qt auto-disconnects. Not 100% airtight in PySide6 — if it crashes in practice, fall back to explicit `widget.destroyed.connect(lambda: get_theme_manager().theme_changed.disconnect(...))`.
- **f-string drift.** A future contributor adds `setStyleSheet(f"color: {c.error};")` in a constructor without an extracted `_rebuild_styles` method, and breaks live switching. Mitigation: the live-switching smoke test will catch any new widget that's missing the wire-up, as long as the test is updated when widgets are added. Document this in the migration section of CLAUDE.md or a top-of-file comment in `theme/live.py`.

## 7. Success criteria

- `grep -rE '#[0-9a-fA-F]{6}|QColor\("white"\)' git_gui/presentation/widgets/` returns only matches inside f-strings reading the theme (or none).
- `grep -r 'TODO(theme)' git_gui/presentation/widgets/` returns nothing.
- `uv run pytest tests/ -v` — all tests pass, including the new tokens and live-switching tests.
- Manual: `uv run python main.py`, in the Python REPL or via a test fixture call `get_theme_manager().set_mode("light")` then `set_mode("dark")` — every visible color updates within one event loop tick, no restart needed.
