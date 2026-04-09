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


def test_custom_panel_disabled_when_mode_is_dark(app, reset_theme):
    get_theme_manager().set_mode("dark")
    dlg = ThemeDialog()
    assert not dlg._custom_panel.isEnabled()


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


def test_reset_restores_dark_defaults(app, reset_theme):
    dlg = ThemeDialog()
    _radios(dlg)["custom"].setChecked(True)
    dlg._working_colors["primary"] = "#abcdef"
    dlg._apply_swatch_color("primary", "#abcdef")
    dlg._on_reset()
    from git_gui.presentation.theme.loader import load_builtin
    expected = load_builtin("dark").colors.primary
    assert dlg._working_colors["primary"] == expected


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
