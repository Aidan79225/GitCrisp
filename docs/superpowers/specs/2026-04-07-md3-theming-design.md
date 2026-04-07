# MD3 Theming for GitStack — Design

**Date:** 2026-04-07
**Status:** Draft for review

## Goal

Replace the ~84 inline style/color/font sites scattered across `git_gui/presentation/widgets/` with a centralized theming system inspired by Material Design 3. The system must support light/dark modes that follow macOS system appearance, runtime theme switching without restart, and forward-compatibility with user-defined themes loaded from JSON files.

## Non-Goals

- MD3 seed-color tonal palette generator (deferred to its own spec).
- A Settings dialog UI for choosing theme — only the programmatic API is in scope.
- A full MD3 component library (FilledButton, Card, etc.).
- Accessibility / contrast auditing.
- Motion / animation tokens.

## Architecture

A new package `git_gui/presentation/theme/` containing:

```
theme/
├── __init__.py           # re-exports ThemeManager, Theme
├── tokens.py             # Theme dataclass (frozen) + sub-dataclasses
├── loader.py             # Theme.load(path: Path) -> Theme; strict validation
├── qss_template.py       # QSS template string + render(theme) -> str
├── manager.py            # ThemeManager (QObject singleton) + theme_changed signal
├── settings.py           # JSON read/write of user settings
└── builtin/
    ├── light.json
    └── dark.json         # shipped as package resources
```

### Components

**`tokens.py` — Theme dataclass**

A frozen dataclass `Theme` composed of nested frozen dataclasses:

- `Theme.colors` — minimal MD3 color roles plus git-domain extras:
  - MD3 roles: `primary`, `on_primary`, `primary_container`, `on_primary_container`, `secondary`, `on_secondary`, `error`, `on_error`, `surface`, `on_surface`, `surface_variant`, `on_surface_variant`, `surface_container`, `surface_container_high`, `outline`, `outline_variant`, `background`, `on_background`.
  - Git extras: `diff_added_bg`, `diff_added_fg`, `diff_removed_bg`, `diff_removed_fg`, `graph_lane_colors` (list[str]), `ref_badge_branch_bg`, `ref_badge_tag_bg`, `ref_badge_remote_bg`.
  - All values are hex strings (`"#RRGGBB"` or `"#RRGGBBAA"`); the dataclass exposes a helper `as_qcolor(name) -> QColor`.
- `Theme.typography` — `title_large`, `title_medium`, `body_large`, `body_medium`, `body_small`, `label_large`, `label_medium`. Each is a `TextStyle(family, size, weight, letter_spacing)`. The dataclass exposes `as_qfont(name) -> QFont`.
- `Theme.shape` — `corner_xs=4`, `corner_sm=8`, `corner_md=12`, `corner_lg=16`.
- `Theme.spacing` — `xs=4`, `sm=8`, `md=16`, `lg=24`, `xl=32`.
- `Theme.name: str` — human-readable identifier ("Light", "Dark", or a user theme name).
- `Theme.is_dark: bool` — used by widgets that need to branch on luminance.

The schema is small enough for a user to hand-edit but covers everything the existing widgets need. New tokens are added as widgets demand them; YAGNI applies.

**`loader.py`**

`Theme.load(path: Path) -> Theme` parses a JSON file into the dataclass. Validation is strict:

- Missing required keys raise `ThemeValidationError` with the offending path (`colors.primary`).
- Unknown keys raise `ThemeValidationError` (prevents silent typos in user themes).
- Hex colors are validated by regex.

`Theme.load_builtin(name: Literal["light", "dark"]) -> Theme` loads via `importlib.resources`.

**`qss_template.py`**

A module-level `QSS_TEMPLATE: str` containing the global stylesheet for standard Qt widgets (QPushButton, QLineEdit, QTabBar, QTabWidget, QScrollBar, QMenu, QMenuBar, QToolTip, QDialog, QGroupBox, QComboBox, QCheckBox, QRadioButton, QListView, QTreeView, QTableView, QHeaderView, QSplitter, QStatusBar). Placeholders use `{token}` syntax (e.g. `{colors.surface}`, `{shape.corner_md}`).

`render(theme: Theme) -> str` walks the template and substitutes placeholders by attribute lookup. A unit test asserts the rendered output contains no leftover `{` placeholders.

Where existing widgets need a non-default look, they call `setObjectName("DiffStatHeader")` and the global QSS targets `QLabel#DiffStatHeader { ... }`. This keeps per-widget styling out of widget code.

**`manager.py` — ThemeManager**

```python
class ThemeManager(QObject):
    theme_changed = Signal(object)  # Theme

    def __init__(self, app: QApplication): ...
    @property
    def current(self) -> Theme: ...
    def set_mode(self, mode: Literal["system", "light", "dark"]) -> None: ...
    @property
    def mode(self) -> str: ...
```

Behavior:

- On construction: reads `settings.json` → resolves effective `Theme` → renders QSS → calls `app.setStyleSheet(...)` *before* the main window is shown.
- Connects to `QGuiApplication.styleHints().colorSchemeChanged`. When mode is `"system"`, this signal triggers a re-resolve and re-apply.
- `set_mode(...)` persists to `settings.json`, re-resolves, re-renders QSS, re-applies, and emits `theme_changed(new_theme)`.
- Singleton: a module-level `get_theme_manager()` accessor; tests can reset it.

**`settings.py`**

Tiny JSON read/write for `<QStandardPaths.AppDataLocation>/GitStack/settings.json`. Today the file holds a single key:

```json
{ "theme_mode": "system" }
```

Functions: `load_settings() -> dict`, `save_settings(data: dict) -> None`. Missing file → returns defaults. Malformed file → logs a warning and returns defaults (do not crash on a broken settings file).

The same directory will later host `themes/*.json` for user themes; colocation is intentional.

## Data Flow

```
ThemeManager (singleton, owned by main entrypoint)
   ├── settings.json → mode
   ├── builtin/{light|dark}.json → Theme
   ├── render QSS → app.setStyleSheet(...)
   └── emit theme_changed(theme)
                │
                ├── standard widgets: nothing to wire (QSS handles them)
                └── custom-painted widgets:
                     - take ThemeManager in __init__
                     - store self._theme = mgr.current
                     - connect mgr.theme_changed → self._on_theme_changed
                     - slot updates self._theme and calls self.update()
                     - paint() reads colors/fonts from self._theme
```

System-mode flow on macOS appearance change:

```
macOS appearance flips
    → QGuiApplication.styleHints().colorSchemeChanged
    → ThemeManager re-resolves (mode == "system")
    → re-renders QSS, re-applies
    → emits theme_changed
    → custom-painted widgets repaint
```

## Migration of Existing Widgets

The 13 widgets currently using inline styles fall into two groups:

### Group A — QSS-covered (standard Qt forms)

`clone_dialog.py`, `insight_dialog.py`, `log_panel.py`, `sidebar.py`, `repo_list.py`, `working_tree.py`, `commit_detail.py`, `diff.py`

- Delete inline `setStyleSheet(...)` calls.
- Where a widget needs distinct styling, assign `setObjectName("...")` and add a corresponding rule to the global QSS template.
- No constructor changes, no signal wiring.

### Group B — Custom-painted

`graph.py`, `graph_lane_delegate.py`, `ref_badge_delegate.py`, `commit_info_delegate.py`, `diff_block.py`, `hunk_diff.py`

- Constructor takes `theme_manager: ThemeManager` (or reads via `get_theme_manager()`).
- Stores `self._theme = theme_manager.current`.
- Connects `theme_manager.theme_changed` → `self._on_theme_changed(theme)` which updates `self._theme` and calls `self.update()` (or `viewport().update()` for delegates' parent views).
- Replaces hardcoded `QColor(...)` and `QFont(...)` literals inside `paint()` with `self._theme.colors.as_qcolor("...")` / `self._theme.typography.as_qfont("...")`.

The migration replaces every site found by the audit (`setStyleSheet`, `QColor(`, `QFont(`, hardcoded `background-color`, `color:`, `font-size`).

## Initialization Order

In `main.py` (or wherever `QApplication` is constructed today):

1. Construct `QApplication`.
2. Construct `ThemeManager(app)` — this reads settings and applies the global QSS.
3. Construct the main window. Pass the manager (or rely on `get_theme_manager()`) into widgets that need it.
4. Show the main window.

The QSS must be applied before any widget is shown to avoid an unstyled-flash.

## Testing

- **`tests/presentation/theme/test_loader.py`**
  - Loads `builtin/light.json` and `builtin/dark.json`; asserts all required token paths are populated.
  - Rejects a JSON with a missing required key.
  - Rejects a JSON with an unknown key.
  - Rejects a malformed hex color.
- **`tests/presentation/theme/test_qss_render.py`**
  - Renders the QSS template against both builtin themes; asserts no `{` placeholders remain.
  - Asserts a non-empty stylesheet (sanity).
- **`tests/presentation/theme/test_manager.py`**
  - `set_mode("dark")` emits `theme_changed` exactly once with a dark `Theme`.
  - With `mode == "system"`, faking `colorSchemeChanged` flips the active theme.
  - `set_mode` persists to `settings.json`; reconstructing the manager picks it up.
- **`tests/presentation/theme/test_settings.py`**
  - Round-trip save/load.
  - Missing file → defaults.
  - Malformed file → defaults + warning, no crash.
- Existing widget tests must still pass after migration. Spot-check one Group B widget (probably `graph.py`) for re-paint on theme change.

All tests run via `uv run pytest tests/ -v` per `CLAUDE.md`.

## Forward-Compatibility for User Themes

The loader already accepts an arbitrary `Path`, and the dataclass schema *is* the JSON schema. A future "user themes" feature only needs to:

1. List `*.json` files in `<app data>/GitStack/themes/`.
2. Add a third option to `set_mode` (or a separate `set_custom_theme(path)`).
3. Persist the chosen path in `settings.json`.

No changes to widgets, QSS template, or token taxonomy will be required.

## Risks & Open Questions

- **QSS feature gaps:** Qt's QSS does not support every CSS property. If MD3 elevation shadows can't be expressed in QSS for a given widget, we accept a flat surface for that widget rather than fall back to per-widget painting. Documented as a known limitation.
- **macOS native widget bleed-through:** On macOS, some widgets ignore QSS background colors. If encountered, we'll use `setAttribute(Qt.WA_StyledBackground)` or palette overrides as targeted fixes during migration; not designed up front.
- **Custom widgets that currently style themselves via `setStyleSheet`:** During migration, audit each one; if it really needs widget-local styling, it joins Group B and reads from `self._theme` rather than constructing a stylesheet string.

## Deliverables

1. New package `git_gui/presentation/theme/` with the modules described above.
2. `builtin/light.json` and `builtin/dark.json` covering the full token set.
3. Migrated widgets (Groups A and B) with all inline style sites removed or replaced.
4. Test suite under `tests/presentation/theme/`.
5. Initialization wired into the app entrypoint.
