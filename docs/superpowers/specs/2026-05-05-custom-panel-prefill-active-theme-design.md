# Custom panel pre-fills from active theme

## Context

The Theme dialog's Custom panel always seeds its swatches from the
hard-coded Dark builtin (`theme_dialog.py:194` — `load_builtin("dark")`).
This is unhelpful for two reasons:

1. **Inspection.** A user who wants to confirm the currently-applied
   theme's hex values has no way to see them in the UI. They can switch
   to Custom hoping to read off the swatches, but instead see Dark's
   values regardless of what's actually live.
2. **Customization workflow.** When the user wants to tweak the active
   theme rather than start from Dark, they have to manually re-pick
   every color. The pre-fill should match what they're looking at.

The fix is to seed Custom from `self._mgr.current` at dialog open.

## Scope

- **One Python file modified:** `git_gui/presentation/dialogs/theme_dialog.py`.
- **One test file updated:** `tests/presentation/dialogs/test_theme_dialog.py`
  (one test renamed/updated, one test added).
- **No JSON, QSS, or other widget changes.**

## Change

`self._dark_defaults` → `self._base_theme`, sourced from the live theme
manager:

```python
# Before (line 194):
self._dark_defaults = load_builtin("dark")

# After:
self._base_theme = self._mgr.current
```

Rename and rewire the three call sites:

| Old name | New name | Notes |
|---|---|---|
| `self._dark_defaults` | `self._base_theme` | Type unchanged (`Theme`). |
| `_reset_to_dark_defaults_state()` | `_reset_to_base_state()` | Body unchanged except it reads `self._base_theme.colors`. |
| Reads in `_write_custom_theme()` | (same body, new attribute name) | The Custom JSON now inherits typography/shape/spacing from whatever was active when the dialog opened, not always Dark. |

The base is captured **once at dialog `__init__`**. Toggling the mode
radio inside the dialog doesn't re-seed — that radio represents what
Apply will switch *to*, not the source of truth for current values.

## Reset behavior

The Reset button calls `_reset_to_base_state()` and therefore reverts
working colors to the active theme's values (not Dark's, as before).

This is more intuitive: Reset undoes color edits made in the current
session. Users who specifically want a Dark baseline can switch to Dark
mode in the main UI, then re-open the dialog — the base will be Dark.

## Edge cases

- **Saved Custom file exists.** `_maybe_load_existing_custom_theme()`
  runs after the pre-fill in `__init__`. It overrides working colors
  with the saved file. Existing behavior preserved.
- **Mode = "system".** `self._mgr.current` resolves to whichever theme
  the system mode currently provides. Pre-fill uses that. Correct.
- **Mode = "custom".** `self._mgr.current` is the loaded custom theme.
  Pre-fill matches the saved custom values; then
  `_maybe_load_existing_custom_theme` re-loads from disk (same values).
  No conflict.

## What stays untouched

- The mode radio buttons, their callbacks, the typography slider, and
  every other dialog control.
- All theme infrastructure: `loader.py`, `manager.py`, `tokens.py`,
  `qss_template.py`, theme JSON files.
- Existing tests that don't touch the rename surface
  (`test_apply_custom_writes_file_and_sets_mode`, mode-toggle tests,
  cancel test, etc.).

## Critical files

- `git_gui/presentation/dialogs/theme_dialog.py` — five edit points:
  - Constructor reference at line ~194 (the `load_builtin` call).
  - `_reset_to_dark_defaults_state` definition (line 243) — rename and
    body update.
  - Call site of `_reset_to_dark_defaults_state` in `_build_custom_panel`
    (line 199).
  - Call site in `_on_reset` (line 322).
  - `_write_custom_theme` references to `self._dark_defaults` (lines
    337, 349).
  - `_maybe_load_existing_custom_theme` reference at line 389.
- `tests/presentation/dialogs/test_theme_dialog.py`:
  - Update `test_reset_restores_dark_defaults` (line 92) — rename to
    `test_reset_restores_active_theme_values`, set Light mode first,
    assert against Light's `primary`.
  - Add `test_custom_panel_prefills_from_active_theme` — sets Light
    mode, opens dialog, clicks Custom radio, asserts
    `dlg._working_colors["surface"] == "#eff5fd"`.

## Verification

**Automated:**
```
uv run pytest tests/presentation/dialogs/test_theme_dialog.py -v
uv run pytest tests/ -q
```
The renamed test plus the new test both pass; full suite continues to
pass.

**Manual:**
1. `uv run python main.py`. Switch to Light via the theme dialog (Apply,
   close the dialog).
2. Re-open the theme dialog. Click the Custom radio. The swatches
   should now display the Light theme's hex codes — confirming
   `surface = #eff5fd`, `on_surface = #1a2533`,
   `on_surface_variant = #475260`, etc.
3. Without changing anything, click Cancel. (No write to custom_theme
   file.)
4. Open the dialog again, click Custom, change a swatch, click Reset.
   The swatch should revert to Light's value (not Dark's).
5. Switch to Dark mode, then re-open the dialog and click Custom — now
   swatches show Dark's hex codes.
