# Custom panel sections expand in any mode

## Context

After landing the live-update + active-theme pre-fill changes, the
Custom panel's swatches now show the active theme's hex codes — but
the panel is disabled (`setEnabled(False)`) whenever mode is not
Custom, so the QToolBox section headers ("Brand", "Surface", "Diff",
etc.) don't respond to clicks. To browse all sections of the palette
the user has to switch into Custom mode, defeating the inspection
use case.

The fix: stop disabling the panel container, and instead silently
ignore swatch clicks when not in Custom mode. The QToolBox stays
navigable in every mode; editing is still gated to Custom.

## Scope

- **One Python file modified:**
  `git_gui/presentation/dialogs/theme_dialog.py`.
- **One test file updated:**
  `tests/presentation/dialogs/test_theme_dialog.py` — one new test
  asserting the toolbox is interactive in Light mode and that swatch
  clicks are no-ops outside Custom.

## Change

Two edits in `theme_dialog.py`:

**1. `_on_mode_radio_toggled`** — drop the `setEnabled` call:

```python
def _on_mode_radio_toggled(self, _checked: bool) -> None:
    mode = self._selected_mode()
    # was: self._custom_panel.setEnabled(mode == "custom")
    if mode == self._base_theme_mode:
        return
    ...
```

The `_custom_panel` stays enabled across all modes. Section navigation
in the QToolBox works normally.

**2. `_open_picker` and `_open_lane_picker`** — add an early-return
guard so clicks outside Custom mode do nothing:

```python
def _open_picker(self, token: str) -> None:
    if self._selected_mode() != "custom":
        return
    from PySide6.QtWidgets import QColorDialog
    ...

def _open_lane_picker(self, idx: int) -> None:
    if self._selected_mode() != "custom":
        return
    from PySide6.QtWidgets import QColorDialog
    ...
```

The guard is at the top, before any state mutation. Click events still
fire (Qt has no way to "un-route" them after `setEnabled(True)`), but
the handler returns immediately.

The construction-time `setEnabled` call in `__init__` (the line
`self._custom_panel.setEnabled(self._selected_mode() == "custom")`) is
also removed — without the runtime toggle there's no reason to start
disabled.

## What stays the same

- `_on_apply` continues to gate `_write_custom_theme` on
  `mode == "custom"`. Edits made (impossibly) while in Light/Dark/System
  would not persist. With the guards above, edits cannot be made there
  in the first place — the Apply gate is now a defense-in-depth.
- The typography slider remains draggable in all modes. It mutates
  only `_typo_label` and the slider position; nothing about the active
  theme. Apply discards it unless mode is Custom.
- Reset (`_on_reset`) keeps its existing `if mode != "custom": return`
  guard — clicking Reset in Light/Dark mode is already a no-op.

## Verification

**Automated:**
```
uv run pytest tests/presentation/dialogs/test_theme_dialog.py -v
uv run pytest tests/ -q
```

The new test (added in this change):

```python
def test_custom_panel_remains_navigable_outside_custom_mode(app, reset_theme):
    """In Light/Dark/System mode the QToolBox section headers must still be
    clickable so the user can browse all swatches; only individual swatch
    clicks are no-ops."""
    mgr = get_theme_manager()
    mgr.set_mode("light")
    dlg = ThemeDialog()
    assert dlg._custom_panel.isEnabled()
    assert dlg._toolbox.isEnabled()
    # Swatch clicks in non-custom mode should not change _working_colors.
    original = dlg._working_colors["primary"]
    dlg._open_picker("primary")  # would otherwise pop a modal — guard returns early
    assert dlg._working_colors["primary"] == original
```

`dlg._open_picker("primary")` would normally pop a modal `QColorDialog`
in tests. The guard short-circuits before that, so the test runs
synchronously.

**Manual:**
1. `uv run python main.py`. Open the theme dialog while on Light.
2. Without switching to Custom, click the QToolBox section headers
   ("Brand", "Surface", "Diff", "Misc", "Graph lanes"). Each section
   should expand to show its swatches with hex codes.
3. Click a swatch. Nothing should happen — no color picker pops up.
4. Switch the radio to Custom. Now click a swatch — the color picker
   appears as before.
