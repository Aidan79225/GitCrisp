# MD3 Theming — Follow-ups

**Date:** 2026-04-07
**Status:** Backlog (next branch)
**Parent spec:** `2026-04-07-md3-theming-design.md`

## What landed in `feat/md3-theming`

- `git_gui/presentation/theme/` package: `tokens.py`, `loader.py`, `qss_template.py`, `manager.py`, `settings.py`, `builtin/{light,dark}.json`.
- `Theme` (frozen dataclass) with `Colors`, `Typography`, `TextStyle`, `Shape`, `Spacing`.
- Strict JSON loader with hex validation; `load_builtin("light"|"dark")` via `importlib.resources`.
- `ThemeManager(QObject)` with `theme_changed` signal, `set_mode(system|light|dark)`, and `colorSchemeChanged` listener for live macOS appearance follow.
- Settings persisted to `<AppData>/GitStack/settings.json`.
- 8 widgets migrated to read colors from theme via lazy getters: `sidebar`, `clone_dialog`, `log_panel`, `insight_dialog`, `repo_list`, `working_tree`, `commit_detail`, `diff`, `graph`, `graph_lane_delegate`, `ref_badge_delegate`, `commit_info_delegate`, `diff_block`.
- Global QSS template intentionally **empty** — see "Why empty QSS" below.
- 143 tests passing (19 new theme tests + existing).

## Why the global QSS is empty

The first cut shipped a full QSS template (`QWidget { background-color: ...; }` etc.). It looked wrong:

1. The `QWidget` rule cascaded to every descendant, including `QScrollBar`. Once any QSS touches a scrollbar (even via inheritance), Qt drops native rendering and uses stylesheet mode — scrollbars looked broken.
2. Existing widgets still own per-widget `setStyleSheet` calls, so the global QSS fought them.

For now `qss_template.py` returns `""`. The theme system is fully wired, but JSON edits only affect colors that widgets read directly via `get_theme_manager().current.colors.*`. Adding back targeted QSS rules (using `setObjectName` selectors, never `QWidget`) is on the backlog.

## Open follow-ups

### 1. New theme tokens for currently-TODO'd literals

These widgets contain hardcoded values marked `# TODO(theme)`:

- **Status colors** (M/A/D/R in `_DELTA_BADGE` dicts in `working_tree.py` and `diff.py`):
  - `#1f6feb` modified, `#238636` added, `#da3633` deleted, `#f0883e` renamed, `#8b949e` unknown
  - Add tokens: `status_modified`, `status_added`, `status_deleted`, `status_renamed`, `status_unknown`
- **Insight dialog**: `GREEN` `#238636`, `RED` `#da3633` — same as above (additions/deletions). Reuse `status_added`/`status_deleted`.
- **HEAD branch color** (`ref_badge_delegate.COLOR_HEAD = #238636`): add `branch_head_bg`. Same green as `status_added` but semantically distinct — keep as own token.
- **Diff block accents** (`diff_block.py`):
  - `HEADER_STYLE color: #e3b341` (yellow file header) → `diff_file_header_fg`
  - `HUNK_HEADER_COLOR = #58a6ff` (blue hunk header) → `diff_hunk_header_fg`
- **Diff added/removed line backgrounds** (`diff_block.py`): `QColor(35, 134, 54, 80)` and `QColor(248, 81, 73, 80)` are RGBA over `surface_container_high`. Add `diff_added_overlay`, `diff_removed_overlay` (hex8 with alpha) to the token schema.
- **Badge text color** (`commit_info_delegate.py`, `ref_badge_delegate.py`, `working_tree.py`, `diff.py`, `insight_dialog.py`): all use `QColor("white")` for text on colored badges. Add `on_badge` token (defaults to `#ffffff`).
- **Other `QColor("white")` text** in `commit_detail.py` and `insight_dialog.py` title labels — these are default foreground on dark surfaces. Should read `on_surface` once evaluated.
- **Graph button hover overlay** (`graph.py`): `rgba(255, 255, 255, 30)` semi-transparent overlay. Add `hover_overlay` token (hex8) or special-case it.

### 2. Live theme switching (no restart)

Currently `set_mode()` updates `current` and emits `theme_changed`, but the migrated widgets read theme **lazily on each paint** via getter functions — they will pick up the new theme on the next repaint, but only for sites that go through the getter. Sites that cached the value (e.g. `make_file_block` building a stylesheet string once) won't refresh until rebuilt.

Two options:
- **A)** Add `theme_changed` listeners in widgets to call `update()` / rebuild stylesheets on the signal.
- **B)** Document that theme change requires restart; only system-mode auto-switch is live.

A is the better UX but is more wiring.

### 3. Settings UI

A simple dialog (or menu item) with a 3-radio "Appearance: System / Light / Dark". Persists via `ThemeManager.set_mode`. Out of scope for the original spec; small standalone follow-up.

### 4. User-defined themes

Loader already accepts an arbitrary `Path`, schema is JSON-stable. Need:
- Auto-discovery of `<AppData>/GitStack/themes/*.json`.
- `set_mode` extension to accept a custom theme name/path.
- Theme picker in the Settings UI.

### 5. Targeted global QSS

Once widgets are theme-aware, add back narrow QSS rules using object-name selectors so they don't cascade and break native rendering. Likely candidates: dialog button row spacing, line edit focus ring, tab bar selected color. **Never** put rules on bare `QWidget` or `QScrollBar`.

### 6. MD3 seed-color tonal palette generator

Originally listed as a non-goal — still deferred. Would let the user pick one seed color and auto-generate the full palette per the MD3 algorithm. Significant work; own spec.

## Risks / known issues

- The lazy-getter pattern means `get_theme_manager()` is called on every paint. Cheap (singleton lookup + attribute read), but worth profiling if paint becomes hot in graph view.
- Tests now depend on `tests/conftest.py` initializing `ThemeManager` at session scope. Any new test that touches a theme-aware module inherits this fixture automatically.

## Known limitations carried over from Batch 1

### Diff text colors do not update on live theme switch

**Symptom:** After Batch 1 landed live theme switching for most widgets, switching the theme at runtime updates everything except the colored text *inside an already-rendered diff* (`+`/`-` line foregrounds, hunk header text inside the QPlainTextEdit, diff line backgrounds). The user must close and re-open the file's diff to see the new colors. The file frame border, file header label, and hunk header label *outside* the text edit do refresh live.

**Root cause:** `git_gui/presentation/widgets/diff_block.py::make_diff_formats()` builds `QTextCharFormat` and `QTextBlockFormat` objects once and bakes them onto each text block via cursor inserts in `render_hunk_*`. There is no `QSyntaxHighlighter` to call `rehighlight()` on. To refresh, the entire diff text would need to be re-rendered with new format instances.

**What it would take to fix:**
1. Either wrap the diff rendering in a `QSyntaxHighlighter` subclass whose `highlightBlock` reads colors from the current theme on each call (then `rehighlight()` does the work), OR
2. Store the source `Hunk` data on the file block, expose a `rerender()` method that wipes the QPlainTextEdit and replays `render_hunk_*` with fresh formats, and call it from the file block's `_rebuild()` closure.

Option 2 is the smaller change and matches the existing rendering pipeline; option 1 is more idiomatic Qt but a bigger refactor.

**Workaround for users today:** close the file and re-open it after switching theme.

**Tracking:** address in the next batch alongside Settings UI / user themes work, or as a standalone small PR.
