# Custom Panel Live Radio Update — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Theme dialog's Custom panel re-seed itself whenever the mode radio changes, so the user can preview Light/Dark/System/Custom hex codes without having to Apply and re-open.

**Architecture:** (1) Promote `ThemeManager._resolve_theme()` to a public `theme_for_mode(mode)` method so the dialog can resolve any mode without changing the active mode. (2) Extend `_on_mode_radio_toggled` to call it, swap `_base_theme`, and refresh swatches. (3) Decouple typography scaling from the swatch source by adding a separate `_typography_base = load_builtin("dark")` attribute that the round-trip math relies on instead of `_base_theme`.

**Tech Stack:** PySide6 dialog and theme manager. Tests via `uv run pytest`.

**Spec:** `docs/superpowers/specs/2026-05-05-custom-panel-live-radio-update-design.md`

---

## File Structure

- **Modify:** `git_gui/presentation/theme/manager.py` — add `theme_for_mode(mode: str) -> Theme`; refactor `_resolve_theme` to a one-liner that delegates.
- **Modify:** `git_gui/presentation/dialogs/theme_dialog.py` — extend `_on_mode_radio_toggled`, add `_base_theme_mode` and `_typography_base` attributes in `__init__`, switch `_write_custom_theme` and `_maybe_load_existing_custom_theme` to use `_typography_base.typography` for size math, drop the at-open `if mode == "custom"` Dark guard.
- **Modify:** `tests/presentation/dialogs/test_theme_dialog.py` — add one new test for the live-refresh behavior.

---

## Task 1: Promote `_resolve_theme` to public `theme_for_mode`

**Files:**
- Modify: `git_gui/presentation/theme/manager.py`

- [ ] **Step 1: Add the new public method**

In `git_gui/presentation/theme/manager.py`, find:

```python
    def _resolve_theme(self) -> Theme:
        if self._mode == "light":
            return load_builtin("light")
        if self._mode == "dark":
            return load_builtin("dark")
        if self._mode == "custom":
            return self._load_custom_or_fallback()
        return self._system_theme()
```

Replace with:

```python
    def theme_for_mode(self, mode: str) -> Theme:
        """Resolve a mode name to a Theme without changing the active mode."""
        if mode not in _VALID_MODES:
            raise ValueError(f"Invalid theme mode: {mode}")
        if mode == "light":
            return load_builtin("light")
        if mode == "dark":
            return load_builtin("dark")
        if mode == "custom":
            return self._load_custom_or_fallback()
        return self._system_theme()

    def _resolve_theme(self) -> Theme:
        return self.theme_for_mode(self._mode)
```

- [ ] **Step 2: Run the manager tests**

Run: `rtk uv run pytest tests/presentation/theme/test_manager.py -v`

Expected: all PASSED. The refactor is behavior-preserving for all existing callers.

- [ ] **Step 3: Commit**

```bash
rtk git add git_gui/presentation/theme/manager.py
rtk git commit -m "$(cat <<'EOF'
refactor(theme): expose theme_for_mode for ad-hoc mode resolution

Promote the private _resolve_theme into a public theme_for_mode that
takes a mode argument. The existing _resolve_theme keeps its name
and signature but delegates. Lets callers (specifically the Theme
dialog) resolve any mode to a Theme without mutating the manager.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Make Custom panel update on radio toggle

This task TDDs the user-visible behavior. The test fails until `_on_mode_radio_toggled` is rewired.

**Files:**
- Modify: `tests/presentation/dialogs/test_theme_dialog.py`
- Modify: `git_gui/presentation/dialogs/theme_dialog.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/presentation/dialogs/test_theme_dialog.py` after the existing tests:

```python
def test_radio_toggle_refreshes_custom_panel(app, reset_theme):
    """Switching the mode radio inside the dialog must re-seed _base_theme
    and update _working_colors so the user can preview different themes
    without having to Apply + reopen."""
    mgr = get_theme_manager()
    mgr.set_mode("dark")
    dlg = ThemeDialog()

    from git_gui.presentation.theme.loader import load_builtin
    dark_surface = load_builtin("dark").colors.surface
    light_surface = load_builtin("light").colors.surface
    assert dlg._working_colors["surface"] == dark_surface

    _radios(dlg)["light"].setChecked(True)
    assert dlg._working_colors["surface"] == light_surface

    _radios(dlg)["dark"].setChecked(True)
    assert dlg._working_colors["surface"] == dark_surface
```

- [ ] **Step 2: Run the new test and confirm it FAILS**

Run: `rtk uv run pytest tests/presentation/dialogs/test_theme_dialog.py::test_radio_toggle_refreshes_custom_panel -v`

Expected: FAILED. The current `_on_mode_radio_toggled` only toggles `_custom_panel` enabled state; `_working_colors` never refreshes.

- [ ] **Step 3: Refactor the typography baseline in `__init__`**

Open `git_gui/presentation/dialogs/theme_dialog.py`. Find the `_base_theme` initialization in `__init__` (added in the previous task, around line 135):

```python
        # Capture the theme the Custom panel pre-fills from. Normally this
        # is whatever's currently active, so the user sees the live hex
        # codes and can iterate from there. When mode is already "custom",
        # fall back to the Dark builtin: the saved custom theme file stores
        # typography sizes that were generated by scaling Dark's typography,
        # so using anything else as the divisor in
        # _maybe_load_existing_custom_theme would reconstruct the wrong
        # slider position.
        if self._mgr.mode == "custom":
            self._base_theme = load_builtin("dark")
        else:
            self._base_theme = self._mgr.current
```

Replace with:

```python
        # _base_theme drives the Custom panel's swatch pre-fill and is
        # re-seeded whenever the user toggles the mode radio. _base_theme_mode
        # remembers the mode that produced the current pre-fill so the
        # toggle handler can short-circuit no-op refreshes.
        self._base_theme_mode = self._mgr.mode
        self._base_theme = self._mgr.theme_for_mode(self._base_theme_mode)
        # Saved custom theme files store typography sizes generated by
        # scaling Dark's typography. _typography_base is the divisor for
        # the slider's reverse-computation, so it must always be Dark
        # regardless of which radio the user is on.
        self._typography_base = load_builtin("dark")
```

- [ ] **Step 4: Update `_on_mode_radio_toggled` to refresh swatches**

Find the current handler (around line 158):

```python
    def _on_mode_radio_toggled(self, _checked: bool) -> None:
        self._custom_panel.setEnabled(self._selected_mode() == "custom")
```

Replace with:

```python
    def _on_mode_radio_toggled(self, _checked: bool) -> None:
        mode = self._selected_mode()
        self._custom_panel.setEnabled(mode == "custom")
        if mode == self._base_theme_mode:
            return
        self._base_theme_mode = mode
        self._base_theme = self._mgr.theme_for_mode(mode)
        self._reset_to_base_state()
        for token, hex_value in self._working_colors.items():
            self._apply_swatch_color(token, hex_value)
        for i, hex_value in enumerate(self._working_lane_colors):
            self._apply_lane_swatch_color(i, hex_value)
```

- [ ] **Step 5: Switch `_write_custom_theme` typography math to `_typography_base`**

Find the `_write_custom_theme` method. The previous task changed its first lines to:

```python
        scale = self._typo_slider.value() / 100.0
        base = self._base_theme
```

The body uses `base.typography` for scaled-styles. Update so typography uses `self._typography_base` while everything else (Colors base, is_dark, shape, spacing) keeps using `base = self._base_theme`. The relevant block becomes:

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
```

The rest of `_write_custom_theme` (Colors, lane colors, Theme construction) is unchanged.

- [ ] **Step 6: Switch `_maybe_load_existing_custom_theme` typography math to `_typography_base`**

Find:

```python
        base_size = self._base_theme.typography.body_medium.size
        if base_size > 0:
            ratio = theme.typography.body_medium.size / base_size
```

Replace with:

```python
        base_size = self._typography_base.typography.body_medium.size
        if base_size > 0:
            ratio = theme.typography.body_medium.size / base_size
```

- [ ] **Step 7: Run the new test and confirm PASS**

Run: `rtk uv run pytest tests/presentation/dialogs/test_theme_dialog.py::test_radio_toggle_refreshes_custom_panel -v`

Expected: PASSED.

- [ ] **Step 8: Run the full theme dialog test file**

Run: `rtk uv run pytest tests/presentation/dialogs/test_theme_dialog.py -v`

Expected: all PASSED. Notably:
- `test_base_theme_falls_back_to_dark_when_already_in_custom_mode` (added in previous task) was asserting `_base_theme.name == "Dark"` when reopening with mode = custom. With the new design, `_base_theme` for mode=custom is the saved custom theme (not Dark), so this test needs adjustment — see Step 9.

- [ ] **Step 9: Update `test_base_theme_falls_back_to_dark_when_already_in_custom_mode`**

The previous task added a test that asserted `dlg2._base_theme.name == "Dark"` when reopening in custom mode. With the new design, `_base_theme` is the saved custom theme; the typography fallback is now in `_typography_base`. Rename and rewrite:

Replace:

```python
def test_base_theme_falls_back_to_dark_when_already_in_custom_mode(
    app, reset_theme, tmp_path, monkeypatch
):
    """When the dialog opens with mode already 'custom', _base_theme must be
    the Dark builtin (not the loaded custom theme). The saved custom file
    stores typography sizes scaled relative to Dark, so the slider recovery
    in _maybe_load_existing_custom_theme would compute the wrong ratio if
    _base_theme matched the loaded custom theme."""
    from git_gui.presentation.theme import settings as s
    from git_gui.presentation.theme.loader import load_builtin
    monkeypatch.setattr(s, "custom_theme_path", lambda: tmp_path / "custom_theme.json")

    # Save a custom theme with a non-default typography scale.
    dlg1 = ThemeDialog()
    _radios(dlg1)["custom"].setChecked(True)
    dlg1._typo_slider.setValue(150)
    dlg1._on_apply()
    assert get_theme_manager().mode == "custom"

    # Re-open with mode already "custom".
    dlg2 = ThemeDialog()
    assert dlg2._base_theme.name == load_builtin("dark").name
    # And confirm the slider correctly recovered the saved 150% scale,
    # which would not happen if _base_theme were the (already-scaled) custom theme.
    assert dlg2._typo_slider.value() == 150
```

With:

```python
def test_typography_base_is_always_dark_for_round_trip(
    app, reset_theme, tmp_path, monkeypatch
):
    """The slider recovery in _maybe_load_existing_custom_theme divides the
    saved file's body_medium.size by _typography_base. Saved custom files
    store sizes generated by scaling Dark's typography, so _typography_base
    must always be Dark regardless of which radio is selected."""
    from git_gui.presentation.theme import settings as s
    from git_gui.presentation.theme.loader import load_builtin
    monkeypatch.setattr(s, "custom_theme_path", lambda: tmp_path / "custom_theme.json")

    dlg1 = ThemeDialog()
    _radios(dlg1)["custom"].setChecked(True)
    dlg1._typo_slider.setValue(150)
    dlg1._on_apply()
    assert get_theme_manager().mode == "custom"

    dlg2 = ThemeDialog()
    assert dlg2._typography_base.name == load_builtin("dark").name
    assert dlg2._typo_slider.value() == 150
```

- [ ] **Step 10: Run the dialog tests again**

Run: `rtk uv run pytest tests/presentation/dialogs/test_theme_dialog.py -v`

Expected: all PASSED.

- [ ] **Step 11: Run full suite**

Run: `rtk uv run pytest tests/ -q`

Expected: all PASSED.

- [ ] **Step 12: Commit**

```bash
rtk git add git_gui/presentation/dialogs/theme_dialog.py tests/presentation/dialogs/test_theme_dialog.py
rtk git commit -m "$(cat <<'EOF'
feat(theme): Custom panel updates live on radio toggle

Hook the mode radio's toggled signal to re-seed _base_theme and refresh
all swatches. Users can now flip Light/Dark/System/Custom inside the
dialog and see each theme's hex codes without going through Apply
plus reopen. Toggling to a radio whose mode equals the current one is
a no-op, so the QButtonGroup's double-fire semantics don't cause
extra work.

Decouple the typography-scale round-trip from the swatch source by
adding _typography_base, fixed to Dark at __init__. _write_custom_theme
and _maybe_load_existing_custom_theme switch to it for size math.
_base_theme is now free to track the radio without breaking the slider
reverse-computation. The previous at-open "if mode == custom: use Dark"
guard is removed; _typography_base subsumes its job.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Manual verification

**Files:** none modified.

- [ ] **Step 1: Launch the app**

Run: `rtk uv run python main.py`

- [ ] **Step 2: Switch to Dark, then open the theme dialog**

Open Theme dialog → click Dark → Apply. Re-open the dialog.

- [ ] **Step 3: Click each radio and watch the Custom panel**

While the dialog is open:
- Click Light radio (without Apply). Custom panel's swatches should now show Light's hex codes (`surface = #eff5fd`, `on_surface_variant = #475260`, etc.). The Custom panel may be disabled if Custom radio isn't selected — that's fine; the swatch text labels are still readable.
- Click Dark radio. Swatches switch to Dark's values.
- Click System. Swatches match whichever the OS resolves to.
- Click Custom. Swatches show the saved custom theme (or Dark fallback if no save).

If any of these don't update, the rewire didn't take.

- [ ] **Step 4: Click Cancel**

The active theme outside the dialog should be unchanged — none of these clicks invoked Apply.

- [ ] **Step 5: No commit**

Manual verification doesn't produce changes.

---

## Self-Review

**Spec coverage:**
- Public `theme_for_mode` API on ThemeManager → Task 1. ✅
- Live-refresh on radio toggle → Task 2 Steps 3, 4. ✅
- `_typography_base` separation → Task 2 Steps 3 (init), 5 (_write), 6 (_maybe_load). ✅
- Drop the at-open custom-mode Dark guard → Task 2 Step 3 (the old block is replaced wholesale). ✅
- Test for the live-refresh → Task 2 Step 1. ✅
- Update of the prior `_base_theme` test to fit the new design → Task 2 Step 9. ✅

**Placeholder scan:** none — every step has the actual code.

**Type/method consistency:**
- `theme_for_mode(mode: str) -> Theme` matches the type used in the dialog (`self._mgr.theme_for_mode(...)` returns a `Theme`). ✅
- `_typography_base` is a `Theme`; `.typography.body_medium.size` access matches how `_write_custom_theme` and `_maybe_load_existing_custom_theme` use the previous `_dark_defaults.typography` and `_base_theme.typography` references. ✅
- `_base_theme_mode` is a `str`, compared to `mode` (also `str`). ✅
