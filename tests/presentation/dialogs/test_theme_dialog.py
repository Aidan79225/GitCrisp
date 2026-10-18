"""Tests for the ThemeDialog."""

from __future__ import annotations

from pathlib import Path

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


def test_resaving_a_custom_theme_with_baked_in_sizes_writes_unscaled_typography(
    app, reset_theme, tmp_path, monkeypatch
):
    """Files saved before typography_scale existed hold scaled sizes, and
    the runtime scale would otherwise be applied on top of them."""
    import dataclasses
    import json

    from git_gui.presentation.dialogs.theme_dialog import _theme_to_json
    from git_gui.presentation.theme import settings as s
    from git_gui.presentation.theme.loader import load_builtin

    custom_path = tmp_path / "custom_theme.json"
    monkeypatch.setattr(s, "settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(s, "custom_theme_path", lambda: custom_path)
    dark = load_builtin("dark")
    body = dark.typography.body_medium
    baked = dataclasses.replace(
        dark,
        typography=dataclasses.replace(
            dark.typography, body_medium=dataclasses.replace(body, size=body.size * 2)
        ),
    )
    custom_path.write_text(json.dumps(_theme_to_json(baked)), encoding="utf-8")
    dlg = ThemeDialog()
    _radios(dlg)["custom"].setChecked(True)

    dlg._on_apply()

    payload = json.loads(custom_path.read_text(encoding="utf-8"))
    assert payload["typography"]["body_medium"]["size"] == body.size


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


def test_dialog_opens_when_the_saved_custom_theme_is_malformed(
    app, reset_theme, tmp_path, monkeypatch
):
    """Outside Custom mode the app still launches, but the dialog read the
    broken file on open and raised, so View > Appearance did nothing."""
    from git_gui.presentation.theme import settings as s

    custom_path = tmp_path / "custom_theme.json"
    custom_path.write_text("{", encoding="utf-8")
    monkeypatch.setattr(s, "settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(s, "custom_theme_path", lambda: custom_path)
    get_theme_manager().set_mode("dark")

    assert isinstance(ThemeDialog(), QDialog)


def _save_light_based_custom_theme_then_switch_to_dark(tmp_path, monkeypatch) -> Path:
    from git_gui.presentation.theme import settings as s

    custom_path = tmp_path / "custom_theme.json"
    monkeypatch.setattr(s, "settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(s, "custom_theme_path", lambda: custom_path)
    get_theme_manager().set_mode("light")
    dlg = ThemeDialog()
    _radios(dlg)["custom"].setChecked(True)
    dlg._on_apply()
    get_theme_manager().set_mode("dark")
    return custom_path


def test_reapplying_a_saved_custom_theme_keeps_the_tokens_it_has_no_swatch_for(
    app, reset_theme, tmp_path, monkeypatch
):
    """The swatches showed the saved file, but syntax colours and is_dark
    were saved from the active builtin: Light surfaces under Dark's pale
    syntax colours, with no swatch to repair them."""
    import json

    from git_gui.presentation.theme.loader import load_builtin

    custom_path = _save_light_based_custom_theme_then_switch_to_dark(tmp_path, monkeypatch)
    dlg = ThemeDialog()
    _radios(dlg)["custom"].setChecked(True)
    dlg._on_apply()

    payload = json.loads(custom_path.read_text(encoding="utf-8"))
    assert payload["colors"]["syntax_string"] == load_builtin("light").colors.syntax_string
    assert payload["is_dark"] is False


def test_reset_takes_the_unswatched_tokens_back_to_the_active_theme_too(
    app, reset_theme, tmp_path, monkeypatch
):
    import json

    from git_gui.presentation.theme.loader import load_builtin

    custom_path = _save_light_based_custom_theme_then_switch_to_dark(tmp_path, monkeypatch)
    dlg = ThemeDialog()
    _radios(dlg)["custom"].setChecked(True)
    dlg._on_reset()
    dlg._on_apply()

    payload = json.loads(custom_path.read_text(encoding="utf-8"))
    assert payload["colors"]["syntax_string"] == load_builtin("dark").colors.syntax_string


def test_apply_tells_the_user_when_the_settings_cannot_be_saved(
    app, reset_theme, tmp_path, monkeypatch
):
    """The OSError used to escape the slot into the log only, so Apply
    looked as if it did nothing."""
    from PySide6.QtWidgets import QMessageBox

    from git_gui.presentation.theme import settings as s

    not_a_directory = tmp_path / "file"
    not_a_directory.write_text("", encoding="utf-8")
    monkeypatch.setattr(s, "settings_path", lambda: not_a_directory / "settings.json")
    warnings: list[tuple] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    get_theme_manager().set_mode("dark")
    dlg = ThemeDialog()
    _radios(dlg)["light"].setChecked(True)

    dlg._on_apply()

    assert warnings


def test_a_custom_theme_that_cannot_be_saved_leaves_the_settings_as_they_were(
    app, reset_theme, tmp_path, monkeypatch
):
    """The text scale was saved before the custom theme, so Apply reported a
    failure while settings.json already held a scale nobody saw until the
    next launch."""
    from PySide6.QtWidgets import QMessageBox

    from git_gui.presentation.theme import settings as s

    not_a_directory = tmp_path / "file"
    not_a_directory.write_text("", encoding="utf-8")
    monkeypatch.setattr(s, "settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(s, "custom_theme_path", lambda: not_a_directory / "custom_theme.json")
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    get_theme_manager().set_mode("dark")
    before = s.load_settings()
    dlg = ThemeDialog()
    _radios(dlg)["custom"].setChecked(True)
    dlg._typo_slider.setValue(150)

    dlg._on_apply()

    assert s.load_settings() == before


def test_switching_radios_from_a_custom_theme_with_fewer_lanes_keeps_working(
    app, reset_theme, tmp_path, monkeypatch
):
    """The lane buttons are made for the active theme's lanes, and Dark's
    longer list was painted onto buttons that did not exist."""
    import dataclasses
    import json

    from git_gui.presentation.dialogs.theme_dialog import _theme_to_json
    from git_gui.presentation.theme import settings as s
    from git_gui.presentation.theme.loader import load_builtin

    custom_path = tmp_path / "custom_theme.json"
    monkeypatch.setattr(s, "settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(s, "custom_theme_path", lambda: custom_path)
    dark = load_builtin("dark")
    one_lane = dataclasses.replace(
        dark, colors=dataclasses.replace(dark.colors, graph_lane_colors=["#123456"])
    )
    custom_path.write_text(json.dumps(_theme_to_json(one_lane)), encoding="utf-8")
    get_theme_manager().set_mode("custom")
    dlg = ThemeDialog()

    _radios(dlg)["dark"].setChecked(True)

    assert dlg._working_colors["surface"] == dark.colors.surface


def test_swatch_borders_take_the_themes_outline_colour(app, reset_theme):
    get_theme_manager().set_mode("light")
    dlg = ThemeDialog()

    outline = get_theme_manager().current.colors.outline
    assert f"border: 1px solid {outline}" in dlg._swatch_buttons["primary"].styleSheet()
    assert f"border: 1px solid {outline}" in dlg._lane_buttons[0].styleSheet()
