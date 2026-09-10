# Custom Panel Pre-fill From Active Theme — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `ThemeDialog`'s Custom panel seed its swatches and Reset behavior from the currently-active theme instead of always Dark.

**Architecture:** Replace the hard-coded `load_builtin("dark")` with `self._mgr.current` at dialog `__init__`, captured into a renamed attribute `self._base_theme`. Two existing test expectations change accordingly (one rename + assertion swap, one new test).

**Tech Stack:** PySide6 dialog (`git_gui/presentation/dialogs/theme_dialog.py`). Tests use `pytest` via `uv run pytest`.

**Spec:** `docs/superpowers/specs/2026-05-05-custom-panel-prefill-active-theme-design.md`

---

## File Structure

- **Modify:** `git_gui/presentation/dialogs/theme_dialog.py` — rename `self._dark_defaults` → `self._base_theme`, source it from `self._mgr.current`, rename `_reset_to_dark_defaults_state()` → `_reset_to_base_state()`, update three call sites.
- **Modify:** `tests/presentation/dialogs/test_theme_dialog.py` — rename one test and rewrite its body, add one new test.

Files **not** changed: theme JSON, loader, manager, tokens, qss_template, any other widget.

---

## Task 1: Pre-fill Custom panel from active theme

This task uses TDD. The two updated test assertions will fail against the current code (Reset returns Dark's `primary`, working_colors seeded from Dark). After the dialog rewire, both pass.

**Files:**
- Modify: `git_gui/presentation/dialogs/theme_dialog.py`
- Modify: `tests/presentation/dialogs/test_theme_dialog.py`

- [ ] **Step 1: Rewrite the existing reset test**

Open `tests/presentation/dialogs/test_theme_dialog.py`. Locate the test at line 92:

```python
def test_reset_restores_dark_defaults(app, reset_theme):
    dlg = ThemeDialog()
    _radios(dlg)["custom"].setChecked(True)
    dlg._working_colors["primary"] = "#abcdef"
    dlg._apply_swatch_color("primary", "#abcdef")
    dlg._on_reset()
    from git_gui.presentation.theme.loader import load_builtin
    expected = load_builtin("dark").colors.primary
    assert dlg._working_colors["primary"] == expected
```

Replace it with:

```python
def test_reset_restores_active_theme_values(app, reset_theme):
    mgr = get_theme_manager()
    mgr.set_mode("light")
    dlg = ThemeDialog()
    _radios(dlg)["custom"].setChecked(True)
    dlg._working_colors["primary"] = "#abcdef"
    dlg._apply_swatch_color("primary", "#abcdef")
    dlg._on_reset()
    from git_gui.presentation.theme.loader import load_builtin
    expected = load_builtin("light").colors.primary
    assert dlg._working_colors["primary"] == expected
```

- [ ] **Step 2: Add the new pre-fill test**

Append this test immediately after the renamed one (so reset/pre-fill tests sit together):

```python
def test_custom_panel_prefills_from_active_theme(app, reset_theme):
    mgr = get_theme_manager()
    mgr.set_mode("light")
    dlg = ThemeDialog()
    _radios(dlg)["custom"].setChecked(True)
    from git_gui.presentation.theme.loader import load_builtin
    light_colors = load_builtin("light").colors
    assert dlg._working_colors["surface"] == light_colors.surface
    assert dlg._working_colors["on_surface"] == light_colors.on_surface
    assert dlg._working_colors["on_surface_variant"] == light_colors.on_surface_variant
```

- [ ] **Step 3: Run the two tests and confirm they FAIL**

Run: `rtk uv run pytest tests/presentation/dialogs/test_theme_dialog.py::test_reset_restores_active_theme_values tests/presentation/dialogs/test_theme_dialog.py::test_custom_panel_prefills_from_active_theme -v`

Expected: 2 FAILED. The reset test fails because the current implementation resets to Dark's `primary` (`#0070cc` or similar) but the test expects Light's `primary` (`#79c0ff`). The pre-fill test fails because `_working_colors["surface"]` is Dark's surface, not Light's `#eff5fd`.

If either passes unexpectedly, stop — the assertions don't actually exercise the new behavior.

- [ ] **Step 4: Update `theme_dialog.py` — rename the attribute and source**

Open `git_gui/presentation/dialogs/theme_dialog.py`. In `_build_custom_panel()` (around line 161), find:

```python
        # --- Working colour state, prefilled from dark ---
        self._dark_defaults = load_builtin("dark")
        self._working_colors: dict[str, str] = {}
        self._working_lane_colors: list[str] = []
        self._swatch_buttons: dict[str, QPushButton] = {}
        self._lane_buttons: list[QPushButton] = []
        self._reset_to_dark_defaults_state()
```

Replace with:

```python
        # --- Working colour state, prefilled from the currently-active theme ---
        self._base_theme = self._mgr.current
        self._working_colors: dict[str, str] = {}
        self._working_lane_colors: list[str] = []
        self._swatch_buttons: dict[str, QPushButton] = {}
        self._lane_buttons: list[QPushButton] = []
        self._reset_to_base_state()
```

The `from git_gui.presentation.theme.loader import load_builtin` import a few lines above is still needed by `_maybe_load_existing_custom_theme` and the test file references — leave it alone.

- [ ] **Step 5: Rename `_reset_to_dark_defaults_state` and rewire its body**

Locate the method at line 243:

```python
    def _reset_to_dark_defaults_state(self) -> None:
        c = self._dark_defaults.colors
        self._working_colors = {}
        for _, tokens in _GROUPS:
            for token in tokens:
                self._working_colors[token] = getattr(c, token)
        self._working_lane_colors = list(c.graph_lane_colors)
        if hasattr(self, "_typo_slider"):
            self._typo_slider.setValue(_TYPOGRAPHY_SCALE_DEFAULT)
            self._typo_label.setText(f"{_TYPOGRAPHY_SCALE_DEFAULT}%")
```

Replace with:

```python
    def _reset_to_base_state(self) -> None:
        c = self._base_theme.colors
        self._working_colors = {}
        for _, tokens in _GROUPS:
            for token in tokens:
                self._working_colors[token] = getattr(c, token)
        self._working_lane_colors = list(c.graph_lane_colors)
        if hasattr(self, "_typo_slider"):
            self._typo_slider.setValue(_TYPOGRAPHY_SCALE_DEFAULT)
            self._typo_label.setText(f"{_TYPOGRAPHY_SCALE_DEFAULT}%")
```

Only two lines change (the `def` and the first body line).

- [ ] **Step 6: Update the `_on_reset` call site**

In `_on_reset()` (around line 319), find:

```python
    def _on_reset(self) -> None:
        if self._selected_mode() != "custom":
            return
        self._reset_to_dark_defaults_state()
```

Replace `self._reset_to_dark_defaults_state()` with `self._reset_to_base_state()`. Rest of the method is unchanged.

- [ ] **Step 7: Update `_write_custom_theme` to use `self._base_theme`**

In `_write_custom_theme()` (line 328), there are two references to `self._dark_defaults`. Find:

```python
        scale = self._typo_slider.value() / 100.0
        dark = self._dark_defaults
```

Replace with:

```python
        scale = self._typo_slider.value() / 100.0
        base = self._base_theme
```

Then change every `dark.` reference in the function body to `base.`. There are five references: `dark.typography` (1×), `dark.colors` (1×), `dark.is_dark` (1×), `dark.shape` (1×), `dark.spacing` (1×). After this step the function reads:

```python
    def _write_custom_theme(self) -> None:
        import json
        import dataclasses
        from git_gui.presentation.theme import settings as _settings
        from git_gui.presentation.theme.tokens import (
            Colors, Theme, Typography, TextStyle,
        )

        scale = self._typo_slider.value() / 100.0
        base = self._base_theme

        scaled_styles = {}
        for field in dataclasses.fields(Typography):
            base_style: TextStyle = getattr(base.typography, field.name)
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

        path = _settings.custom_theme_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_theme_to_json(custom_theme), indent=2))
```

Note the inner loop variable changed from `base` (the original code's name for a `TextStyle`) to `base_style` to avoid shadowing the outer `base` (the Theme). This is a small clarity improvement that falls out of the rename.

- [ ] **Step 8: Update `_maybe_load_existing_custom_theme`**

In `_maybe_load_existing_custom_theme()` (line 367), find the reference at line 389:

```python
        dark_size = self._dark_defaults.typography.body_medium.size
        if dark_size > 0:
            ratio = theme.typography.body_medium.size / dark_size
```

Replace with:

```python
        base_size = self._base_theme.typography.body_medium.size
        if base_size > 0:
            ratio = theme.typography.body_medium.size / base_size
```

Two lines change (the assignment and the comparison/divisor). The rest of the block is unchanged.

- [ ] **Step 9: Run the two new/updated tests and confirm they PASS**

Run: `rtk uv run pytest tests/presentation/dialogs/test_theme_dialog.py::test_reset_restores_active_theme_values tests/presentation/dialogs/test_theme_dialog.py::test_custom_panel_prefills_from_active_theme -v`

Expected: 2 PASSED.

- [ ] **Step 10: Run the entire theme_dialog test file**

Run: `rtk uv run pytest tests/presentation/dialogs/test_theme_dialog.py -v`

Expected: all PASSED. The other tests (mode toggle, apply, cancel, typography scale, reopen-prefills-from-saved) don't touch the renamed surface or assume Dark-as-base, so they should be unaffected. `test_typography_scale_applied_on_save` continues to pass because the `reset_theme` fixture leaves Dark mode active when that test runs, so active = Dark, so the typography base is still Dark.

- [ ] **Step 11: Run the full suite**

Run: `rtk uv run pytest tests/ -q`

Expected: all PASSED. (Whatever count the suite is at — this change adds 1 net test relative to its starting point, since one was renamed/rewritten and one was added.)

- [ ] **Step 12: Commit**

```bash
rtk git add git_gui/presentation/dialogs/theme_dialog.py tests/presentation/dialogs/test_theme_dialog.py
rtk git commit -m "$(cat <<'EOF'
feat(theme): Custom panel pre-fills from active theme

Replace the hard-coded Dark seed in ThemeDialog with self._mgr.current,
captured at dialog __init__ as self._base_theme. Reset, _write_custom_theme,
and _maybe_load_existing_custom_theme all switch to the new attribute.
Net effect: clicking Custom while Light is active now shows Light's
hex codes; clicking Reset reverts to whatever was active when the
dialog opened.

See docs/superpowers/specs/2026-05-05-custom-panel-prefill-active-theme-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Manual verification

This is a fast eyeball check that the rewire actually surfaces the right values in the running UI.

**Files:** none modified.

- [ ] **Step 1: Launch the app**

Run: `rtk uv run python main.py`

- [ ] **Step 2: Switch to Light, then re-open the dialog**

Open Theme dialog → click Light → Apply. Re-open the Theme dialog. Click the Custom radio. The swatches should now display Light's hex codes:
- `surface` → `#eff5fd`
- `on_surface` → `#1a2533`
- `on_surface_variant` → `#475260`
- `surface_container_high` → `#c9d6e9`
- `outline` → `#bcc7da`

If they show Dark's `#ffffff` / `#1f2328` etc., the rewire didn't take — re-check Step 4 of Task 1.

- [ ] **Step 3: Test Reset on Light**

Still in the Custom panel (Light is the base). Click any swatch — say `primary` — and pick a different color via the picker. Click Reset. The swatch should revert to Light's `primary` (`#79c0ff`), not Dark's.

- [ ] **Step 4: Switch to Dark, repeat**

Cancel the dialog. Open Theme dialog → click Dark → Apply. Re-open. Click Custom. Swatches now show Dark's hex codes. Reset reverts to Dark's values. Confirms the rewire reads from whatever's active.

- [ ] **Step 5: No commit**

Manual verification doesn't produce changes. If a swatch ever shows the wrong value or Reset reverts to the wrong palette, surface the issue.

---

## Self-Review

**Spec coverage:**
- Rename + source switch (`self._dark_defaults` → `self._base_theme = self._mgr.current`) → Task 1 Step 4. ✅
- Rename `_reset_to_dark_defaults_state` → `_reset_to_base_state` → Task 1 Step 5. ✅
- Three call sites updated (Step 4 already updates the build-time call; Steps 6, 7, 8 cover the others). ✅
- Reset behavior change → Task 1 Step 6 + verified by the rewritten test in Step 1. ✅
- Edge cases (saved custom file, mode = system, mode = custom) → existing `_maybe_load_existing_custom_theme` continues to work after Step 8; behavior is unchanged for those modes. ✅
- Test updates → Task 1 Steps 1–2 (rename existing + add new). ✅

**Placeholder scan:** none — every step has the actual code or command.

**Type/method consistency:**
- `_base_theme` is consistently a `Theme` (the type returned by `_mgr.current` and `load_builtin`). ✅
- `_reset_to_base_state` is referenced in three places (definition + 2 call sites at Steps 5 and 6); all use the same name. ✅
- The variable rename in `_write_custom_theme` (Step 7) introduces `base` and `base_style` to avoid shadowing — both are local to the function and don't affect the rest of the dialog. ✅
