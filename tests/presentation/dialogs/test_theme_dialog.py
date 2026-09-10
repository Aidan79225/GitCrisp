"""Tests for the ThemeDialog."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QRadioButton

from git_gui.presentation.dialogs.theme_dialog import ThemeDialog
from git_gui.presentation.theme import get_theme_manager


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def reset_theme():
    yield
    get_theme_manager().set_mode("dark")


def _radios(dialog: ThemeDialog) -> dict[str, QRadioButton]:
    """Return {mode_name: radio} for the dialog's mode buttons."""
    return {
        radio.property("mode"): radio
        for radio in dialog.findChildren(QRadioButton)
        if radio.property("mode") in ("system", "light", "dark", "custom")
    }


def test_dialog_constructs(app, reset_theme):
    dlg = ThemeDialog()
    assert isinstance(dlg, QDialog)
    radios = _radios(dlg)
    assert set(radios.keys()) == {"system", "light", "dark", "custom"}


def test_initial_radio_matches_current_mode(app, reset_theme):
    mgr = get_theme_manager()
    mgr.set_mode("dark")
    dlg = ThemeDialog()
    assert _radios(dlg)["dark"].isChecked()


def test_apply_with_light_radio_sets_mode(app, reset_theme):
    mgr = get_theme_manager()
    mgr.set_mode("dark")
    dlg = ThemeDialog()
    _radios(dlg)["light"].setChecked(True)
    dlg._on_apply()
    assert mgr.mode == "light"


def test_cancel_does_not_change_mode(app, reset_theme):
    mgr = get_theme_manager()
    mgr.set_mode("dark")
    dlg = ThemeDialog()
    _radios(dlg)["light"].setChecked(True)
    dlg._on_cancel()
    assert mgr.mode == "dark"


def test_swatch_click_outside_custom_mode_is_noop(app, reset_theme):
    """The Custom panel stays enabled in all modes (so QToolBox sections are
    navigable), but clicking a swatch in non-Custom mode is silently
    ignored — _working_colors does not change."""
    get_theme_manager().set_mode("dark")
    dlg = ThemeDialog()
    original = dlg._working_colors["primary"]
    dlg._open_picker("primary")
    assert dlg._working_colors["primary"] == original


def test_custom_panel_enables_when_custom_radio_clicked(app, reset_theme):
    dlg = ThemeDialog()
    _radios(dlg)["custom"].setChecked(True)
    assert dlg._custom_panel.isEnabled()


def test_apply_custom_writes_file_and_sets_mode(app, reset_theme, tmp_path, monkeypatch):
    from git_gui.presentation.theme import settings as s

    monkeypatch.setattr(s, "custom_theme_path", lambda: tmp_path / "custom_theme.json")

    dlg = ThemeDialog()
    _radios(dlg)["custom"].setChecked(True)
    dlg._working_colors["primary"] = "#abcdef"
    dlg._on_apply()

    assert (tmp_path / "custom_theme.json").exists()
    assert get_theme_manager().mode == "custom"

    import json

    payload = json.loads((tmp_path / "custom_theme.json").read_text())
    assert payload["colors"]["primary"] == "#abcdef"


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


def test_typography_scale_persists_to_settings(app, reset_theme, tmp_path, monkeypatch):
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


def test_typography_base_is_always_dark_for_round_trip(app, reset_theme, tmp_path, monkeypatch):
    """The slider recovery in _maybe_load_existing_custom_theme divides the
    saved file's body_medium.size by _typography_base. Saved custom files
    store sizes generated by scaling Dark's typography, so _typography_base
    must always be Dark regardless of which radio is selected."""
    from git_gui.presentation.theme import settings as s
    from git_gui.presentation.theme.loader import load_builtin

    monkeypatch.setattr(s, "settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(s, "custom_theme_path", lambda: tmp_path / "custom_theme.json")

    dlg1 = ThemeDialog()
    _radios(dlg1)["custom"].setChecked(True)
    dlg1._typo_slider.setValue(150)
    dlg1._on_apply()
    assert get_theme_manager().mode == "custom"

    dlg2 = ThemeDialog()
    assert dlg2._typography_base.name == load_builtin("dark").name
    assert dlg2._typo_slider.value() == 150


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
