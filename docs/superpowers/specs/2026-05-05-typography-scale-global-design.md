# Typography scale becomes a global setting

## Context

The Theme dialog has a typography-scale slider (50–200%) that today
only takes effect in Custom mode — `_on_apply` writes the scaled
sizes into `custom_theme.json`, and `ThemeManager._apply` reads the
JSON's `body_medium.size` to set `QApplication.font()`. In any other
mode (System / Light / Dark) the slider is draggable but Apply does
nothing with it: the active theme's `body_medium.size` is fixed by
the JSON file shipped in `git_gui/presentation/theme/builtin/`.

The fix is to lift the scale out of the per-theme JSON and into a
global user setting. The slider then drives that setting; the manager
applies the scale at runtime regardless of which theme is active.

## Scope

- **Modify:** `git_gui/presentation/theme/settings.py` — add
  `typography_scale` to `DEFAULTS`.
- **Modify:** `git_gui/presentation/theme/manager.py` — read
  `typography_scale` in `_apply`; multiply `body_medium.size`.
- **Modify:** `git_gui/presentation/dialogs/theme_dialog.py` — slider
  reads/writes the setting; stop baking scale into custom JSON; stop
  recovering scale from custom JSON.
- **Update:** `tests/presentation/dialogs/test_theme_dialog.py` —
  update `test_typography_scale_applied_on_save` and the typography
  assertions in `test_reopen_dialog_prefills_from_saved_file` /
  `test_typography_base_is_always_dark_for_round_trip` to match the
  new flow (slider value lives in settings, not in the JSON).
- **Add a manager test** that verifies `_apply` honors the setting.

## Settings schema

```python
DEFAULTS = {
    "theme_mode": "system",
    "avatar_gravatar_enabled": True,
    "typography_scale": 1.0,  # new — float, 0.5..2.0 in 0.1 steps
}
```

The dialog converts between integer slider values (50..200) and the
float setting (0.5..2.0).

## ThemeManager change

Inside `_apply`, where the QFont is constructed:

```python
body = self._current.typography.body_medium
font = QFont(self._app.font())
if body.family:
    font.setFamily(body.family)
if body.size > 0:
    scale = float(load_settings().get("typography_scale", 1.0))
    size = max(1, round(body.size * scale))
    if sys.platform == "darwin":
        from PySide6.QtGui import QFontDatabase
        native_pt = QFontDatabase.systemFont(
            QFontDatabase.SystemFont.GeneralFont
        ).pointSize()
        if native_pt > 0:
            size = round(size * native_pt / 9)
    font.setPointSize(size)
```

The scale multiplication happens before the macOS native-pt
adjustment. Order is mathematically irrelevant (multiplication
commutes), but applying scale first reads more naturally.

`_apply` is called any time the manager refreshes (`set_mode(force=…)`
in particular), so the dialog can trigger it after writing the new
scale to settings.

## Dialog changes

**`__init__` / typography slider init:** read scale from settings
instead of defaulting to 100%.

```python
saved_scale = float(_settings.load_settings().get("typography_scale", 1.0))
slider_value = round(saved_scale * 100 / _TYPOGRAPHY_SCALE_STEP) * _TYPOGRAPHY_SCALE_STEP
slider_value = max(_TYPOGRAPHY_SCALE_MIN, min(_TYPOGRAPHY_SCALE_MAX, slider_value))
self._typo_slider.setValue(slider_value)
self._typo_label.setText(f"{slider_value}%")
```

Place this where `_typo_slider.setValue(_TYPOGRAPHY_SCALE_DEFAULT)`
currently is.

**`_on_apply`:** write the slider value to settings, then proceed as
before. Insert before the `_write_custom_theme()` call:

```python
def _on_apply(self) -> None:
    mode = self._selected_mode()
    self._save_typography_scale()
    if mode == "custom":
        self._write_custom_theme()
    self._mgr.set_mode(mode, force=True)
    self._save_avatar_setting()
    self.accept()

def _save_typography_scale(self) -> None:
    scale = self._typo_slider.value() / 100.0
    data = _settings.load_settings()
    if data.get("typography_scale") == scale:
        return
    data["typography_scale"] = scale
    _settings.save_settings(data)
```

`set_mode(force=True)` ensures `_apply` runs even if the mode didn't
change — needed so the new scale takes effect immediately when the
user just dragged the slider in (say) Light mode.

**`_write_custom_theme`:** stop baking the scale. Write Dark's
typography un-scaled:

```python
custom_theme = Theme(
    name="Custom",
    is_dark=base.is_dark,
    colors=Colors(**colors_kwargs),
    typography=self._typography_base.typography,  # was: Typography(**scaled_styles)
    shape=base.shape,
    spacing=base.spacing,
)
```

The whole `scaled_styles` block becomes dead code — remove it. The
imports of `dataclasses.fields(Typography)`, `TextStyle` for the loop,
and `scale = self._typo_slider.value() / 100.0` go with it.

**`_maybe_load_existing_custom_theme`:** stop recovering scale from
the saved JSON. Remove the typography-ratio block entirely. The
slider already reflects the settings value from `__init__`.

**`_reset_to_base_state`:** stop resetting the slider to 100%. The
slider should show the saved settings value, not a fixed default,
when the user clicks Reset. Remove these lines:

```python
        if hasattr(self, "_typo_slider"):
            self._typo_slider.setValue(_TYPOGRAPHY_SCALE_DEFAULT)
            self._typo_label.setText(f"{_TYPOGRAPHY_SCALE_DEFAULT}%")
```

Reset's purpose is to revert color edits; it shouldn't fight the
typography setting.

## Backward compat

- If a saved `custom_theme.json` has previously-scaled typography
  (`body_medium.size = 15` from a 1.5× scale), it stays as-is in the
  file but no longer drives the slider. On next Apply in Custom mode,
  `_write_custom_theme` overwrites with Dark's un-scaled typography.
  Self-corrects.
- During the brief window between version upgrade and first Apply,
  `_apply` reads `body_medium.size = 15` from the legacy JSON and
  multiplies by `typography_scale` (default 1.0) → 15 pt. That's
  visually identical to the user's previous Custom theme. No surprise.
- If the user had a non-default scale before this change, they'll see
  100% slider on first dialog open after upgrade. That's the cleanest
  behavior — the prior scale was implicit; now it's explicit.

## Tests

**Modify** `test_typography_scale_applied_on_save` (line ~103). The
old assertion checked the saved JSON contained scaled typography:

```python
dark_body = load_builtin("dark").typography.body_medium.size
assert payload["typography"]["body_medium"]["size"] == round(dark_body * 1.5)
```

New assertion: the JSON contains Dark's un-scaled sizes; the scale
went to settings instead:

```python
from git_gui.presentation.theme import settings as s
dark_body = load_builtin("dark").typography.body_medium.size
assert payload["typography"]["body_medium"]["size"] == dark_body
assert s.load_settings()["typography_scale"] == 1.5
```

**Modify** `test_reopen_dialog_prefills_from_saved_file` (line ~119).
The old assertion checked the slider recovered from the JSON; now it
recovers from settings. The setup is unchanged; the assertion is
identical because the slider value is round-tripped via settings.

**Modify** `test_typography_base_is_always_dark_for_round_trip` (added
in the previous task). The old test asserted `_typography_base.name ==
"Dark"` and `_typo_slider.value() == 150`. The first assertion still
holds (we still keep `_typography_base = load_builtin("dark")` even
though the typography baseline isn't read from JSON anymore — kept
for the colors_kwargs base in `_write_custom_theme`). The second
still holds because the slider's value is now restored from settings.

**Add** `test_typography_scale_applies_in_light_mode` to
`tests/presentation/theme/test_manager.py`:

```python
def test_typography_scale_applies_in_light_mode(app, isolated_settings):
    from git_gui.presentation.theme import settings as s
    from PySide6.QtGui import QFont
    s.save_settings({"theme_mode": "light", "typography_scale": 1.5})
    mgr = ThemeManager(app)
    body = mgr.current.typography.body_medium
    expected_pt = max(1, round(body.size * 1.5))
    # macOS adjusts further; on other platforms expect exact match.
    import sys
    if sys.platform != "darwin":
        assert app.font().pointSize() == expected_pt
```

## Verification

**Automated:**
```
uv run pytest tests/presentation/theme/test_manager.py -v
uv run pytest tests/presentation/dialogs/test_theme_dialog.py -v
uv run pytest tests/ -q
```

**Manual:**
1. `uv run python main.py` while on Light mode.
2. Open theme dialog, drag the slider to 150%, click Apply. Confirm
   text in graph panel, commit list, and diff blocks looks ~50%
   larger.
3. Restart the app. The 150% scale should persist.
4. Open dialog again. Slider should show 150%. Drag back to 100%,
   Apply. Text returns to normal size.
5. Switch to Dark, scale 80%, Apply. Confirm text is smaller.
6. Switch to Custom, scale 100%, Apply. Re-open: slider is at 100%.
   Saved `custom_theme.json` should now have Dark's body_medium.size
   (10), not a scaled value.
