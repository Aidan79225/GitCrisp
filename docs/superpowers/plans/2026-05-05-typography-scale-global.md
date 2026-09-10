# Typography Scale Global Setting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the Theme dialog's typography-scale slider from per-Custom-JSON state to a global `typography_scale` setting that takes effect uniformly across System / Light / Dark / Custom modes.

**Architecture:** New setting `typography_scale` (float, default 1.0) lives in `settings.json`. `ThemeManager._apply` multiplies `body_medium.size` by the scale before constructing the `QFont`. `ThemeDialog`'s slider becomes the editor for that setting; `_write_custom_theme` stops baking scaled sizes into the custom JSON.

**Tech Stack:** PySide6 + JSON-based settings. Tests via `uv run pytest`.

**Spec:** `docs/superpowers/specs/2026-05-05-typography-scale-global-design.md`

---

## File Structure

- **Modify:** `git_gui/presentation/theme/settings.py` — add `typography_scale` to `DEFAULTS`.
- **Modify:** `git_gui/presentation/theme/manager.py` — read `typography_scale` in `_apply`, multiply `body_medium.size`.
- **Modify:** `git_gui/presentation/dialogs/theme_dialog.py` — slider reads/writes the setting; remove typography baking and recovery from JSON.
- **Modify:** `tests/presentation/dialogs/test_theme_dialog.py` — update three existing tests for the new flow.
- **Modify:** `tests/presentation/theme/test_manager.py` — add one test asserting the setting applies in non-Custom modes.

---

## Task 1: Add `typography_scale` to settings

**Files:**
- Modify: `git_gui/presentation/theme/settings.py`

- [ ] **Step 1: Add the new key**

In `git_gui/presentation/theme/settings.py`, change:

```python
DEFAULTS = {"theme_mode": "system", "avatar_gravatar_enabled": True}
```

to:

```python
DEFAULTS = {
    "theme_mode": "system",
    "avatar_gravatar_enabled": True,
    "typography_scale": 1.0,
}
```

- [ ] **Step 2: Run the full suite to confirm no break**

Run: `rtk uv run pytest tests/ -q`

Expected: all PASSED. Adding a key to `DEFAULTS` is purely additive.

- [ ] **Step 3: Commit**

```bash
rtk git add git_gui/presentation/theme/settings.py
rtk git commit -m "$(cat <<'EOF'
feat(theme): add typography_scale to settings DEFAULTS

Float, default 1.0. Picked up by ThemeManager._apply (next commit) to
scale body_medium.size at runtime across all themes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: ThemeManager applies the scale

**Files:**
- Modify: `git_gui/presentation/theme/manager.py`
- Modify: `tests/presentation/theme/test_manager.py`

- [ ] **Step 1: Add the failing manager test**

Append to `tests/presentation/theme/test_manager.py`:

```python
def test_typography_scale_applies_to_app_font(app, isolated_settings):
    """When typography_scale is set, _apply scales body_medium.size before
    setting the QApplication font. Verifies the setting actually drives
    text size, not just sits in JSON."""
    import sys
    from git_gui.presentation.theme import settings as s
    from git_gui.presentation.theme.loader import load_builtin
    s.save_settings({"theme_mode": "light", "typography_scale": 1.5})
    mgr = ThemeManager(app)
    body = load_builtin("light").typography.body_medium
    expected_pt = max(1, round(body.size * 1.5))
    if sys.platform != "darwin":
        assert app.font().pointSize() == expected_pt
    else:
        # macOS scales further by native_pt / 9; just confirm scale shifted
        # the font to a larger size than the unscaled equivalent would.
        unscaled = max(1, round(body.size * 1.0))
        assert app.font().pointSize() > unscaled
```

- [ ] **Step 2: Run the test and confirm FAIL**

Run: `rtk uv run pytest tests/presentation/theme/test_manager.py::test_typography_scale_applies_to_app_font -v`

Expected: FAIL on the size assertion (the manager doesn't read the setting yet).

- [ ] **Step 3: Update `_apply` in `manager.py`**

In `git_gui/presentation/theme/manager.py`, find the existing `_apply` body:

```python
        if body.size > 0:
            import sys
            size = body.size
            if sys.platform == "darwin":
                from PySide6.QtGui import QFontDatabase
                native_pt = QFontDatabase.systemFont(
                    QFontDatabase.SystemFont.GeneralFont
                ).pointSize()
                # Theme sizes are calibrated for Windows (~9 pt body).
                # Scale up proportionally for macOS (~13 pt native body).
                if native_pt > 0:
                    size = round(body.size * native_pt / 9)
            font.setPointSize(size)
```

Replace with:

```python
        if body.size > 0:
            import sys
            scale = float(load_settings().get("typography_scale", 1.0))
            size = max(1, round(body.size * scale))
            if sys.platform == "darwin":
                from PySide6.QtGui import QFontDatabase
                native_pt = QFontDatabase.systemFont(
                    QFontDatabase.SystemFont.GeneralFont
                ).pointSize()
                # Theme sizes are calibrated for Windows (~9 pt body).
                # Scale up proportionally for macOS (~13 pt native body).
                if native_pt > 0:
                    size = round(size * native_pt / 9)
            font.setPointSize(size)
```

The change is in two places: `size = body.size` becomes `size = max(1, round(body.size * scale))`, and the macOS branch's `body.size * native_pt / 9` becomes `size * native_pt / 9` (so the scale carries through).

- [ ] **Step 4: Run the test and confirm PASS**

Run: `rtk uv run pytest tests/presentation/theme/test_manager.py::test_typography_scale_applies_to_app_font -v`

Expected: PASSED.

- [ ] **Step 5: Run the full manager test file**

Run: `rtk uv run pytest tests/presentation/theme/test_manager.py -v`

Expected: all PASSED. The other manager tests don't assert specific font sizes, so they should be unaffected.

- [ ] **Step 6: Commit**

```bash
rtk git add git_gui/presentation/theme/manager.py tests/presentation/theme/test_manager.py
rtk git commit -m "$(cat <<'EOF'
feat(theme): ThemeManager applies typography_scale at runtime

Multiply body_medium.size by the user's typography_scale setting
before constructing the application QFont. Scale is applied in all
modes (System/Light/Dark/Custom) — the active theme JSON's body size
is now a base value, not the final pixel size. Order: scale first,
then macOS native-pt adjustment, so both compose without surprises.

New manager test asserts that a 1.5× scale produces a 1.5× pointSize
in the QApplication font (with a relaxed assertion on macOS where
native-pt scaling stacks on top).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Dialog reads/writes the setting; stop baking scale into custom JSON

**Files:**
- Modify: `git_gui/presentation/dialogs/theme_dialog.py`
- Modify: `tests/presentation/dialogs/test_theme_dialog.py`

This is the user-facing change — slider behavior in non-Custom modes.

- [ ] **Step 1: Update the slider's initial value to come from settings**

In `theme_dialog.py`, find this block in `_build_custom_panel` (the slider construction, around line 177):

```python
        self._typo_slider = QSlider(Qt.Horizontal)
        self._typo_slider.setRange(_TYPOGRAPHY_SCALE_MIN, _TYPOGRAPHY_SCALE_MAX)
        self._typo_slider.setSingleStep(_TYPOGRAPHY_SCALE_STEP)
        self._typo_slider.setPageStep(_TYPOGRAPHY_SCALE_STEP)
        self._typo_slider.setTickInterval(_TYPOGRAPHY_SCALE_STEP)
        self._typo_slider.setTickPosition(QSlider.TicksBelow)
        self._typo_slider.setValue(_TYPOGRAPHY_SCALE_DEFAULT)
        self._typo_label = QLabel(f"{_TYPOGRAPHY_SCALE_DEFAULT}%")
```

Replace the last two lines (the setValue + QLabel construction) with:

```python
        saved_scale = float(_settings.load_settings().get("typography_scale", 1.0))
        initial_value = round(saved_scale * 100 / _TYPOGRAPHY_SCALE_STEP) * _TYPOGRAPHY_SCALE_STEP
        initial_value = max(_TYPOGRAPHY_SCALE_MIN, min(_TYPOGRAPHY_SCALE_MAX, initial_value))
        self._typo_slider.setValue(initial_value)
        self._typo_label = QLabel(f"{initial_value}%")
```

- [ ] **Step 2: Add `_save_typography_scale` and call it in `_on_apply`**

Find `_on_apply` (around line 299):

```python
    def _on_apply(self) -> None:
        mode = self._selected_mode()
        if mode == "custom":
            self._write_custom_theme()
        self._mgr.set_mode(mode, force=(mode == "custom"))
        self._save_avatar_setting()
        self.accept()
```

Replace with:

```python
    def _on_apply(self) -> None:
        mode = self._selected_mode()
        self._save_typography_scale()
        if mode == "custom":
            self._write_custom_theme()
        # force=True so _apply runs and picks up the new typography_scale
        # even if the mode itself didn't change.
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

Place `_save_typography_scale` immediately after `_on_apply`, mirroring how `_save_avatar_setting` is placed.

- [ ] **Step 3: Stop baking scale into custom JSON in `_write_custom_theme`**

Find `_write_custom_theme` (around line 328). The current body computes `scaled_styles` from the slider:

```python
        scale = self._typo_slider.value() / 100.0
        base = self._base_theme

        scaled_styles = {}
        for field in dataclasses.fields(Typography):
            base_style: TextStyle = getattr(self._typography_base.typography, field.name)
            scaled_styles[field.name] = TextStyle(
                family=base_style.family,
                size=max(1, round(base_style.size * scale)),
                weight=base_style.weight,
                letter_spacing=base_style.letter_spacing,
            )

        colors_kwargs = dict(dataclasses.asdict(base.colors))
        for token, hex_value in self._working_colors.items():
            colors_kwargs[token] = hex_value
        colors_kwargs["graph_lane_colors"] = list(self._working_lane_colors)

        custom_theme = Theme(
            name="Custom",
            is_dark=base.is_dark,
            colors=Colors(**colors_kwargs),
            typography=Typography(**scaled_styles),
            shape=base.shape,
            spacing=base.spacing,
        )
```

Replace with:

```python
        base = self._base_theme

        colors_kwargs = dict(dataclasses.asdict(base.colors))
        for token, hex_value in self._working_colors.items():
            colors_kwargs[token] = hex_value
        colors_kwargs["graph_lane_colors"] = list(self._working_lane_colors)

        custom_theme = Theme(
            name="Custom",
            is_dark=base.is_dark,
            colors=Colors(**colors_kwargs),
            typography=self._typography_base.typography,
            shape=base.shape,
            spacing=base.spacing,
        )
```

The `scale = ...` line and the entire `scaled_styles` block are removed. The unused imports inside `_write_custom_theme` should be pruned: `dataclasses.fields(Typography)` is still needed for nothing inside this method now, but `dataclasses` is still needed for `dataclasses.asdict(base.colors)`. `TextStyle` and `Typography` are no longer used inside this method — remove them from the local `from git_gui.presentation.theme.tokens import (...)` import. After cleanup the imports inside `_write_custom_theme` should read:

```python
        import json
        import dataclasses
        from git_gui.presentation.theme import settings as _settings
        from git_gui.presentation.theme.tokens import Colors, Theme
```

- [ ] **Step 4: Stop recovering scale from JSON in `_maybe_load_existing_custom_theme`**

Find `_maybe_load_existing_custom_theme` (around line 394). At the end of the method, the typography-recovery block reads:

```python
        base_size = self._typography_base.typography.body_medium.size
        if base_size > 0:
            ratio = theme.typography.body_medium.size / base_size
            slider_value = round(ratio * 100 / _TYPOGRAPHY_SCALE_STEP) * _TYPOGRAPHY_SCALE_STEP
            slider_value = max(_TYPOGRAPHY_SCALE_MIN, min(_TYPOGRAPHY_SCALE_MAX, slider_value))
            self._typo_slider.setValue(slider_value)
            self._typo_label.setText(f"{slider_value}%")
```

Delete this entire block. The slider's initial value is already set from settings in Step 1; reading the JSON's typography would now contradict that.

- [ ] **Step 5: Stop resetting the slider in `_reset_to_base_state`**

Find `_reset_to_base_state` (around line 243). Remove the slider-reset lines:

```python
        if hasattr(self, "_typo_slider"):
            self._typo_slider.setValue(_TYPOGRAPHY_SCALE_DEFAULT)
            self._typo_label.setText(f"{_TYPOGRAPHY_SCALE_DEFAULT}%")
```

The method now ends at `self._working_lane_colors = list(c.graph_lane_colors)`.

- [ ] **Step 6: Update `test_typography_scale_applied_on_save`**

In `tests/presentation/dialogs/test_theme_dialog.py`, find:

```python
def test_typography_scale_applied_on_save(app, reset_theme, tmp_path, monkeypatch):
    from git_gui.presentation.theme import settings as s
    monkeypatch.setattr(s, "custom_theme_path", lambda: tmp_path / "custom_theme.json")

    dlg = ThemeDialog()
    _radios(dlg)["custom"].setChecked(True)
    dlg._typo_slider.setValue(150)
    dlg._on_apply()

    import json
    payload = json.loads((tmp_path / "custom_theme.json").read_text())
    from git_gui.presentation.theme.loader import load_builtin
    dark_body = load_builtin("dark").typography.body_medium.size
    assert payload["typography"]["body_medium"]["size"] == round(dark_body * 1.5)
```

Replace with:

```python
def test_typography_scale_persists_to_settings(
    app, reset_theme, tmp_path, monkeypatch
):
    """The slider value is saved to settings.typography_scale on Apply.
    The custom_theme.json keeps Dark's un-scaled typography — the runtime
    scale is the single source of truth across all modes."""
    from git_gui.presentation.theme import settings as s
    monkeypatch.setattr(s, "settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(s, "custom_theme_path", lambda: tmp_path / "custom_theme.json")

    dlg = ThemeDialog()
    _radios(dlg)["custom"].setChecked(True)
    dlg._typo_slider.setValue(150)
    dlg._on_apply()

    assert s.load_settings()["typography_scale"] == 1.5

    import json
    payload = json.loads((tmp_path / "custom_theme.json").read_text())
    from git_gui.presentation.theme.loader import load_builtin
    dark_body = load_builtin("dark").typography.body_medium.size
    assert payload["typography"]["body_medium"]["size"] == dark_body
```

- [ ] **Step 7: Update `test_reopen_dialog_prefills_from_saved_file`**

The slider value now round-trips via settings, not via the JSON. Update the test setup so settings is monkeypatched alongside the custom theme path:

Find:

```python
def test_reopen_dialog_prefills_from_saved_file(app, reset_theme, tmp_path, monkeypatch):
    from git_gui.presentation.theme import settings as s
    monkeypatch.setattr(s, "custom_theme_path", lambda: tmp_path / "custom_theme.json")

    dlg1 = ThemeDialog()
    _radios(dlg1)["custom"].setChecked(True)
    dlg1._working_colors["primary"] = "#123456"
    dlg1._typo_slider.setValue(120)
    dlg1._on_apply()

    dlg2 = ThemeDialog()
    assert dlg2._working_colors["primary"] == "#123456"
    assert dlg2._typo_slider.value() == 120
```

Replace the second line of the body so settings.json is also redirected to tmp:

```python
def test_reopen_dialog_prefills_from_saved_file(app, reset_theme, tmp_path, monkeypatch):
    from git_gui.presentation.theme import settings as s
    monkeypatch.setattr(s, "settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(s, "custom_theme_path", lambda: tmp_path / "custom_theme.json")

    dlg1 = ThemeDialog()
    _radios(dlg1)["custom"].setChecked(True)
    dlg1._working_colors["primary"] = "#123456"
    dlg1._typo_slider.setValue(120)
    dlg1._on_apply()

    dlg2 = ThemeDialog()
    assert dlg2._working_colors["primary"] == "#123456"
    assert dlg2._typo_slider.value() == 120
```

The assertions don't change — the slider still ends up at 120 — but its source is now settings, not the JSON.

- [ ] **Step 8: Update `test_typography_base_is_always_dark_for_round_trip`**

Find this test (added in a previous task). Add the same `settings_path` monkeypatch so settings round-trips correctly:

Find the line:

```python
    monkeypatch.setattr(s, "custom_theme_path", lambda: tmp_path / "custom_theme.json")
```

And add immediately above it:

```python
    monkeypatch.setattr(s, "settings_path", lambda: tmp_path / "settings.json")
```

The rest of the test is unchanged.

- [ ] **Step 9: Run the dialog tests**

Run: `rtk uv run pytest tests/presentation/dialogs/test_theme_dialog.py -v`

Expected: all PASSED. If `test_typography_scale_persists_to_settings` (renamed in Step 6) fails on the assertion `s.load_settings()["typography_scale"] == 1.5`, double-check Step 2's `_save_typography_scale` is being called from `_on_apply` BEFORE `_write_custom_theme`.

- [ ] **Step 10: Run the full suite**

Run: `rtk uv run pytest tests/ -q`

Expected: all PASSED.

- [ ] **Step 11: Commit**

```bash
rtk git add git_gui/presentation/dialogs/theme_dialog.py tests/presentation/dialogs/test_theme_dialog.py
rtk git commit -m "$(cat <<'EOF'
feat(theme): Apply persists typography_scale to settings

The slider in the Theme dialog now drives the global typography_scale
setting (introduced two commits ago). On Apply, the slider value is
saved to settings.json regardless of mode, and ThemeManager re-applies
to pick up the new scale. The user can drag the slider while on
Light/Dark/System and click Apply to see all text resize.

_write_custom_theme stops baking the scale into custom_theme.json —
it now writes Dark's un-scaled typography. _maybe_load_existing_custom_theme
stops recovering scale from the JSON; the slider's initial value comes
from settings.json instead. _reset_to_base_state stops resetting the
slider; Reset is for color edits, not typography.

The "is the slider's value equal to the saved scale" round-trip is now
mediated by settings.json, not by the custom theme file.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Manual verification

**Files:** none modified.

- [ ] **Step 1: Launch the app**

Run: `rtk uv run python main.py`

- [ ] **Step 2: Drag the slider while on Light**

Open the Theme dialog (mode = Light). Drag the typography slider to **150%**. Click Apply. Confirm: text in the graph panel, commit list, file navigator, and diff blocks is visibly larger (~50%).

- [ ] **Step 3: Restart and verify persistence**

Quit the app. Re-launch. Text should still be at 150% scale. Open the dialog: slider should read 150.

- [ ] **Step 4: Reset to 100%**

Drag the slider to 100%, Apply. Text returns to normal.

- [ ] **Step 5: Test in Dark mode**

Switch to Dark, slider 80%, Apply. Text shrinks. Confirms the scale applies independently of mode.

- [ ] **Step 6: Verify Custom mode no longer bakes the scale**

Switch to Custom, slider 110%, Apply. Locate the saved
`custom_theme.json` (under `<AppData>/GitStack/`). Open it. The
`typography.body_medium.size` should equal Dark's value (10 on
Windows), not `round(10 * 1.1) = 11`. The scale lives in
`settings.json`'s `typography_scale: 1.1` instead.

- [ ] **Step 7: No commit**

Manual verification produces no changes.

---

## Self-Review

**Spec coverage:**
- Settings key → Task 1. ✅
- Manager scaling → Task 2. ✅
- Dialog slider read from settings on init → Task 3 Step 1. ✅
- Dialog slider write to settings on apply → Task 3 Step 2. ✅
- Stop baking scale into custom JSON → Task 3 Step 3. ✅
- Stop recovering from JSON → Task 3 Step 4. ✅
- Stop resetting slider on Reset → Task 3 Step 5. ✅
- Test updates → Task 3 Steps 6, 7, 8. ✅
- New manager test → Task 2 Step 1. ✅
- Backward-compat narrative for legacy custom JSONs → covered in spec; no migration code needed since it self-corrects on next Apply. ✅

**Placeholder scan:** none — every step has the actual code or command.

**Type/method consistency:**
- `typography_scale` is a `float` everywhere (settings, manager, dialog). Conversion: slider int → divide by 100; settings float → multiply by 100. ✅
- `set_mode(force=True)` semantics: even when mode unchanged, force=True triggers `_refresh` → `_apply`, picking up the new scale. ✅
