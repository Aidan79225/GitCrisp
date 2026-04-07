# MD3 Theming Batch 3 — Theme Dialog with Custom Editor

**Date:** 2026-04-07
**Status:** Draft for review
**Parent docs:**
- `2026-04-07-md3-theming-design.md` (original)
- `2026-04-07-md3-theming-followups.md` (backlog)
- `2026-04-07-md3-theming-batch2-design.md` (Batch 2)

## Goal

Replace the current `View → Appearance → System / Light / Dark` flat menu with a single `View → Appearance` menu item that opens a **Theme Dialog**. Inside the dialog the user picks one of four modes — **Dark / Light / System / Custom** — and when **Custom** is selected an inline editor lets them tweak colour tokens (grouped by accordion) and a global typography scale, with values prefilled from the Dark theme.

## Non-Goals

- Multi-named custom themes (single file only).
- User-defined themes auto-discovery from a folder.
- Per-style typography size editing (only a global scale).
- Editing graph lane palette as anything other than 8 swatches.
- Editing typography weight / family / letter spacing.
- MD3 seed-color tonal palette generator.

## 1. UX

### Menu change

`View → Appearance` becomes a single `QAction` (no submenu). Clicking it opens the **Theme** dialog, modal, sized roughly 520×640. The existing 3-item submenu and the action group are removed.

### Theme dialog layout

```
┌─ Theme ─────────────────────────────────────┐
│  Mode                                       │
│   ○ System    ● Dark    ○ Light    ○ Custom │
│                                             │
│  ┌─ Custom (enabled only when Custom) ───┐ │
│  │  Typography scale:  [▬▬●▬▬▬]  100%    │ │
│  │                                        │ │
│  │  ▼ Brand                               │ │
│  │     primary                  [#264f78▎]│ │
│  │     on_primary               [#ffffff▎]│ │
│  │     ...                                │ │
│  │  ▶ Surface                             │ │
│  │  ▶ Status badges                       │ │
│  │  ▶ Branches & refs                     │ │
│  │  ▶ Diff                                │ │
│  │  ▶ Graph lanes                         │ │
│  │  ▶ Misc                                │ │
│  │                                        │ │
│  │              [ Reset to dark defaults ]│ │
│  └────────────────────────────────────────┘ │
│                                             │
│              [ Cancel ]    [ Apply ]        │
└─────────────────────────────────────────────┘
```

- **Mode radios** at top, exclusive `QButtonGroup`.
- **Custom panel** below — `QGroupBox` titled "Custom", `setEnabled(False)` unless mode == Custom.
- **Typography scale** — a `QSlider` (50–200, step 10) with a live `QLabel` showing the percentage. Default 100.
- **Accordion groups** — implemented as a `QToolBox` (Qt's built-in accordion: each "page" is a stand-alone section, only one expanded at a time). The 7 pages are listed below in §2.
- **Color row** — each token is a row: `QLabel` with the token name, then a flat coloured swatch button (32×20 px) showing the current value, and a read-only `QLabel` showing the hex string (e.g. `#264f78`). Click the swatch → opens `QColorDialog.getColor` (with `ShowAlphaChannel` for tokens whose name ends in `_overlay`). When the user picks, swatch and label update.
- **Graph lanes** — special row: 8 swatches in a horizontal `QHBoxLayout`, each editable.
- **Reset button** — wipes the dialog's working state and reloads dark defaults into all controls. Does NOT touch saved file until Apply.
- **Cancel** — close without changes (no `set_mode`, no file write).
- **Apply** — close, persist mode, write custom_theme.json if mode is Custom, call `ThemeManager.set_mode(...)`.

### Buttons / interaction

- Switching the mode radio while the dialog is open enables/disables the Custom panel but does NOT live-apply. Apply happens only on the Apply button. Rationale: live-apply would feel chaotic when dragging a slider 50→200, and a Cancel button needs to actually undo something.
- The dialog is **modal**. The user can't poke the main window while it's open.
- No live preview in the main window during editing — only after Apply. Live preview would mean rendering twice and adds complexity for marginal value (the dialog itself uses `Apply` semantics).

## 2. Accordion groups (QToolBox pages)

| Page | Tokens |
|---|---|
| **Brand** | `primary`, `on_primary`, `primary_container`, `on_primary_container`, `secondary`, `on_secondary`, `error`, `on_error` |
| **Surface** | `background`, `on_background`, `surface`, `on_surface`, `surface_variant`, `on_surface_variant`, `surface_container`, `surface_container_high`, `outline`, `outline_variant` |
| **Status badges** | `status_modified`, `status_added`, `status_deleted`, `status_renamed`, `status_unknown`, `on_badge` |
| **Branches & refs** | `branch_head_bg`, `ref_badge_branch_bg`, `ref_badge_tag_bg`, `ref_badge_remote_bg` |
| **Diff** | `diff_added_bg`, `diff_added_fg`, `diff_removed_bg`, `diff_removed_fg`, `diff_added_overlay`, `diff_removed_overlay`, `diff_file_header_fg`, `diff_hunk_header_fg` |
| **Graph lanes** | `graph_lane_colors` (8 swatches) |
| **Misc** | `hover_overlay` |

The page list is data-driven by a constant `_GROUPS` in the dialog module so it's easy to extend.

The accordion is a `QToolBox` (not `QTreeWidget` or hand-rolled collapsible). `QToolBox` is built-in, behaves like a stacked widget where only one "page" is visible at a time, and ships with the right look-and-feel for grouped settings.

## 3. Custom theme storage

### File location

`<QStandardPaths.AppDataLocation>/GitStack/custom_theme.json` — same directory as `settings.json` from Batch 1.

### File schema

A **complete `Theme` JSON** matching the existing strict loader. No sparse format, no overrides, no merging. When the dialog opens with no existing custom_theme.json, it prefills from `load_builtin("dark")`. When the user clicks Apply with mode == Custom, the dialog writes the entire current state to disk.

Why not sparse: keeping the loader strict (existing behaviour) catches typos in user-provided files. A sparse override format would require either a second loader or a merge layer; not worth the complexity for a single-file editor.

### Typography scale storage

The scale is **not** a separate field. The slider's effect is applied to the typography sizes at Apply time:

```python
scale = slider.value() / 100.0   # e.g. 1.25
for style in typography_styles:
    style.size = round(DARK_DEFAULT[style.name].size * scale)
```

When the dialog re-opens, the slider's initial value is reverse-computed from `body_medium.size / DARK_DEFAULT_BODY_MEDIUM`. Round to nearest 10. If the result is wildly off (because the user hand-edited the file), default to 100.

This means the scale is "lossy" round-trip — but the loss is bounded (rounding to nearest 10%) and only matters if the user reopens the dialog. The benefit is no loader schema change.

## 4. ThemeManager changes

A new mode `"custom"` is added. The `mode` attribute now accepts `system | light | dark | custom`. `set_mode("custom")` does:

1. Read `custom_theme.json` from the settings directory.
2. If missing or invalid → log a warning and fall back to `"dark"`.
3. Otherwise `load_theme(path)` (existing strict loader) and apply.

`_resolve_theme()` adds a `custom` branch:

```python
def _resolve_theme(self) -> Theme:
    if self._mode == "light":
        return load_builtin("light")
    if self._mode == "dark":
        return load_builtin("dark")
    if self._mode == "custom":
        return self._load_custom_or_fallback()
    return self._system_theme()  # mode == "system"
```

`_load_custom_or_fallback()` returns the parsed Theme on success or `load_builtin("dark")` on failure (with a `_log.warning`). The mode persists as `"custom"` either way — failure to load doesn't silently demote the user's choice.

`save_settings({"theme_mode": "custom"})` works exactly as today.

## 5. Wiring

### File / module changes

**New:**
- `git_gui/presentation/dialogs/__init__.py` (package marker)
- `git_gui/presentation/dialogs/theme_dialog.py` — `ThemeDialog` class.
- `tests/presentation/dialogs/__init__.py`
- `tests/presentation/dialogs/test_theme_dialog.py`

**Modified:**
- `git_gui/presentation/menus/appearance.py` — replace the 3-action submenu with one action that opens `ThemeDialog`. The `theme_changed` listener (and its checkmark sync) is dropped — there's no checkmark to update on a single menu item.
- `git_gui/presentation/theme/manager.py` — add `"custom"` to `_VALID_MODES`, extend `_resolve_theme`, add `_load_custom_or_fallback`.
- `tests/presentation/menus/test_appearance.py` — drop the old 3-action tests, replace with one test that asserts clicking the action opens a `QDialog`.
- `tests/presentation/theme/test_manager.py` — add a test for `set_mode("custom")` reading from a temp file.

### Public API surface

```python
# git_gui/presentation/dialogs/theme_dialog.py
class ThemeDialog(QDialog):
    def __init__(self, parent: QMainWindow | None = None) -> None: ...

    # Called from buttons:
    def _on_apply(self) -> None: ...      # writes file, set_mode
    def _on_cancel(self) -> None: ...     # close
    def _on_reset(self) -> None: ...      # restore dark defaults
    def _on_swatch_clicked(self, token: str) -> None: ...
```

```python
# git_gui/presentation/menus/appearance.py
def install_appearance_menu(window: QMainWindow) -> None:
    """View → Appearance opens the Theme dialog."""
    bar = window.menuBar()
    view_menu = bar.addMenu("&View")
    action = QAction("&Appearance...", window)
    action.triggered.connect(lambda: ThemeDialog(window).exec())
    view_menu.addAction(action)
```

## 6. Color picker integration

`QColorDialog.getColor` is the standard Qt picker. Usage pattern per swatch:

```python
def _open_picker(self, token: str) -> None:
    current = self._working_colors[token]
    initial = QColor(current)
    options = QColorDialog.ShowAlphaChannel if token.endswith("_overlay") else QColorDialog.ColorDialogOptions()
    chosen = QColorDialog.getColor(initial, self, f"Choose {token}", options=options)
    if chosen.isValid():
        self._set_token(token, _qcolor_to_hex(chosen))
```

`_qcolor_to_hex` returns `#RRGGBB` for opaque colours and `#AARRGGBB` for tokens with alpha (matching the storage format from Batch 1's overlay fix).

## 7. Testing

`tests/presentation/dialogs/test_theme_dialog.py`:

- Construction: dialog opens with current `mgr.mode` selected and Custom panel disabled when mode != custom.
- Switching radio to Custom enables the custom panel; switching back disables it.
- Reset: with Custom selected, change a few token values, click Reset, assert all swatches show dark defaults.
- Apply with mode = Light: closes dialog, `mgr.mode == "light"`, no custom_theme.json written.
- Apply with mode = Custom and modified tokens: writes custom_theme.json, `mgr.mode == "custom"`, the saved file parses cleanly via the existing loader, and the on-disk values match the dialog state.
- Reopen the dialog after a save: prefilled values match the saved file; typography scale slider position roughly matches the saved sizes.
- Cancel: dialog closes, `mgr.mode` unchanged, no file written.

`tests/presentation/theme/test_manager.py` additions:

- `set_mode("custom")` with a valid custom_theme.json applies that theme; `mgr.current.name` matches the file's name.
- `set_mode("custom")` with no file falls back to dark and logs a warning, but `mgr.mode` remains "custom".

`tests/presentation/menus/test_appearance.py` rewrite:

- After `install_appearance_menu(window)`, the View menu has exactly one action labelled "Appearance...".
- Triggering the action constructs a `ThemeDialog` (assert via a monkeypatch on the dialog class).

No pixel-level tests; no `QColorDialog` interaction tests (Qt's modal picker is non-trivial to drive in tests — the swatch click handler is small enough to trust by inspection).

## 8. Risks

- **Long dialog body.** With ~40 colour tokens across 7 accordion pages, even one expanded page can be tall. The `QToolBox` provides a vertical scroll if needed; the dialog itself sets a minimum size and is otherwise resizable.
- **`QColorDialog` on macOS.** The native picker is excellent but takes focus aggressively; alpha support requires `ShowAlphaChannel`. Should "just work" but worth noting.
- **Reverse-computing the typography scale.** If the user hand-edits custom_theme.json with mismatched sizes, the slider will land in an unexpected place. Mitigation: the scale is a UX affordance, not the source of truth — the actual sizes are what `Theme` carries.
- **Hex8 vs. hex6 formats.** Overlay tokens use `#AARRGGBB` (Qt's order). Non-overlay tokens are `#RRGGBB`. The swatch button's display label and `_qcolor_to_hex` helper must respect this distinction.
- **Forward compatibility.** If a future batch adds a new colour token, the dialog's data-driven `_GROUPS` constant must be updated to include it. Forgetting will leave the new token at the dark default in custom mode (acceptable degradation).

## 9. Success criteria

- `View → Appearance...` opens the Theme dialog.
- The 4 mode radios switch the active mode on Apply (Custom requires the custom file to exist or the Apply button writes it).
- Custom mode shows an editable accordion with all colour tokens prefilled from Dark and a typography scale slider.
- Each colour swatch opens `QColorDialog`; the chosen colour appears in the swatch and the hex label.
- The typography scale slider scales every type style's size proportionally on Apply.
- Custom theme persists across app restarts via `<AppData>/GitStack/custom_theme.json`.
- Cancel and Reset behave per the spec.
- All existing 162 tests still pass; new dialog/manager tests pass.
