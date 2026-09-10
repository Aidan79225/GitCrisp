# Custom Panel Always-Expandable Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the Theme dialog's Custom panel enabled in every mode so its QToolBox section headers respond to clicks; gate editing (the color picker) to Custom mode only.

**Architecture:** Drop `setEnabled(False)` on `_custom_panel` from both the constructor and the radio-toggle handler. Add an early-return guard to `_open_picker` and `_open_lane_picker` so swatch clicks outside Custom mode are silently ignored.

**Tech Stack:** PySide6 QDialog. Tests via `uv run pytest`.

**Spec:** `docs/superpowers/specs/2026-05-05-custom-panel-toolbox-always-expandable-design.md`

---

## File Structure

- **Modify:** `git_gui/presentation/dialogs/theme_dialog.py` — three small edits.
- **Modify:** `tests/presentation/dialogs/test_theme_dialog.py` — one new test.

---

## Task 1: Always-expandable sections + guarded swatch clicks

**Files:**
- Modify: `tests/presentation/dialogs/test_theme_dialog.py`
- Modify: `git_gui/presentation/dialogs/theme_dialog.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/presentation/dialogs/test_theme_dialog.py`:

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
    # Swatch clicks in non-custom mode must not change _working_colors,
    # and must not pop a modal QColorDialog (which would hang the test).
    original = dlg._working_colors["primary"]
    dlg._open_picker("primary")
    assert dlg._working_colors["primary"] == original
```

- [ ] **Step 2: Run the new test and confirm FAIL**

Run: `rtk uv run pytest tests/presentation/dialogs/test_theme_dialog.py::test_custom_panel_remains_navigable_outside_custom_mode -v`

Expected: FAIL on the `dlg._custom_panel.isEnabled()` assertion (the panel is currently disabled when mode != custom). If pytest hangs instead of failing, kill it — it means `_open_picker` reached the `QColorDialog.getColor()` modal call. Either way, the test exercises the new behavior.

- [ ] **Step 3: Drop construction-time `setEnabled` call**

Open `git_gui/presentation/dialogs/theme_dialog.py`. Find in `__init__` (around line 137):

```python
        # --- Custom panel ---
        self._custom_panel = self._build_custom_panel()
        self._custom_panel.setEnabled(self._selected_mode() == "custom")
        layout.addWidget(self._custom_panel)
```

Remove the middle line so it reads:

```python
        # --- Custom panel ---
        self._custom_panel = self._build_custom_panel()
        layout.addWidget(self._custom_panel)
```

- [ ] **Step 4: Drop runtime `setEnabled` toggle**

Find `_on_mode_radio_toggled` (around line 158, after the previous tasks). Remove the `setEnabled` line so the handler reads:

```python
    def _on_mode_radio_toggled(self, _checked: bool) -> None:
        mode = self._selected_mode()
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

(The `self._custom_panel.setEnabled(mode == "custom")` line that was previously the second line of this method is gone.)

- [ ] **Step 5: Guard `_open_picker`**

Find `_open_picker` (around line 271). Add the mode guard at the top:

```python
    def _open_picker(self, token: str) -> None:
        if self._selected_mode() != "custom":
            return
        from PySide6.QtWidgets import QColorDialog
        current = self._working_colors[token]
        ...
```

Rest of the method body is unchanged.

- [ ] **Step 6: Guard `_open_lane_picker`**

Find `_open_lane_picker` (around line 287). Add the same guard:

```python
    def _open_lane_picker(self, idx: int) -> None:
        if self._selected_mode() != "custom":
            return
        from PySide6.QtWidgets import QColorDialog
        current = self._working_lane_colors[idx]
        ...
```

Rest unchanged.

- [ ] **Step 7: Run the new test and confirm PASS**

Run: `rtk uv run pytest tests/presentation/dialogs/test_theme_dialog.py::test_custom_panel_remains_navigable_outside_custom_mode -v`

Expected: PASSED.

- [ ] **Step 8: Run the full theme dialog test file**

Run: `rtk uv run pytest tests/presentation/dialogs/test_theme_dialog.py -v`

Expected: all PASSED.

The existing `test_custom_panel_disabled_when_mode_is_dark` (line 63 in the file) needs attention: it asserted `not dlg._custom_panel.isEnabled()` for Dark mode. With this change the panel is always enabled, so this test will fail. Update it in Step 9.

- [ ] **Step 9: Replace the obsolete disabled-panel test**

Find:

```python
def test_custom_panel_disabled_when_mode_is_dark(app, reset_theme):
    get_theme_manager().set_mode("dark")
    dlg = ThemeDialog()
    assert not dlg._custom_panel.isEnabled()
```

Replace with:

```python
def test_swatch_click_outside_custom_mode_is_noop(app, reset_theme):
    """The Custom panel stays enabled in all modes (so QToolBox sections are
    navigable), but clicking a swatch in non-Custom mode is silently
    ignored — _working_colors does not change."""
    get_theme_manager().set_mode("dark")
    dlg = ThemeDialog()
    original = dlg._working_colors["primary"]
    dlg._open_picker("primary")
    assert dlg._working_colors["primary"] == original
```

This replaces the now-meaningless "panel is disabled" assertion with the
actually-meaningful "swatch clicks are no-ops" assertion.

- [ ] **Step 10: Run the dialog tests again**

Run: `rtk uv run pytest tests/presentation/dialogs/test_theme_dialog.py -v`

Expected: all PASSED.

- [ ] **Step 11: Run the full suite**

Run: `rtk uv run pytest tests/ -q`

Expected: all PASSED.

- [ ] **Step 12: Commit**

```bash
rtk git add git_gui/presentation/dialogs/theme_dialog.py tests/presentation/dialogs/test_theme_dialog.py
rtk git commit -m "$(cat <<'EOF'
feat(theme): keep Custom panel sections expandable in any mode

The Custom panel is no longer disabled when mode != custom. Users can
expand the QToolBox sections (Brand, Surface, Diff, etc.) in
Light/Dark/System mode to inspect each token's hex code. Swatch and
lane-button clicks are silently ignored outside Custom mode via early
returns in _open_picker and _open_lane_picker, so accidental clicks
don't pop a color picker that wouldn't persist anyway.

Replace the obsolete test_custom_panel_disabled_when_mode_is_dark with
a positive assertion: clicking a swatch in non-Custom mode is a no-op.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Manual verification

**Files:** none modified.

- [ ] **Step 1: Launch the app**

Run: `rtk uv run python main.py`

- [ ] **Step 2: While on Light, open the theme dialog**

The mode radio is on Light. The Custom panel is visible.

- [ ] **Step 3: Click each QToolBox section header**

"Brand", "Surface", "Status badges", "Branches & refs", "Diff", "Misc", "Graph lanes". Each should expand to reveal its swatches with hex codes.

- [ ] **Step 4: Click a swatch**

Clicking any swatch should do nothing (no color picker pops up). Hex code remains visible on the button.

- [ ] **Step 5: Switch to Custom radio**

Now click a swatch. The QColorDialog should pop up as before.

- [ ] **Step 6: No commit**

Manual verification doesn't produce changes.

---

## Self-Review

**Spec coverage:**
- Drop `_on_mode_radio_toggled` setEnabled call → Step 4. ✅
- Drop construction-time setEnabled call → Step 3. ✅
- Guard `_open_picker` → Step 5. ✅
- Guard `_open_lane_picker` → Step 6. ✅
- New test for the navigable-toolbox behavior → Step 1. ✅
- Replacement for the obsolete disabled-panel test → Step 9. ✅

**Placeholder scan:** none — every step has the actual code.

**Type/method consistency:** `_selected_mode()` returns a `str`, compared to `"custom"`. Both call sites (`_open_picker`, `_open_lane_picker`) use the same comparison form. ✅
