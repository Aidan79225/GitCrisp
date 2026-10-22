"""Tests for the ThemeDialog."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QRadioButton

from git_gui.presentation.dialogs.theme_dialog import ThemeDialog
from git_gui.presentation.theme import get_theme_manager
from git_gui.presentation.theme.tokens import Theme


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def reset_theme():
    yield
    get_theme_manager().set_mode("dark")


@pytest.fixture
def custom_theme_file(tmp_path, monkeypatch) -> Path:
    """Point settings.json and custom_theme.json into this test's own empty
    directory, and return where the custom theme goes (not yet written).

    The suite-wide redirect shares one settings.json across the session, so a
    test that saves or reads the theme files needs a fresh pair of its own.
    """
    from git_gui.presentation.theme import settings as s

    custom_path = tmp_path / "custom_theme.json"
    monkeypatch.setattr(s, "settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(s, "custom_theme_path", lambda: custom_path)
    return custom_path


def _write_custom_theme(path: Path, theme: Theme) -> None:
    """Save *theme* to *path* the way Apply would."""
    import json

    from git_gui.presentation.dialogs.theme_dialog import _theme_to_json

    path.write_text(json.dumps(_theme_to_json(theme)), encoding="utf-8")


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


def test_apply_custom_writes_file_and_sets_mode(app, reset_theme, custom_theme_file):
    dlg = ThemeDialog()
    _radios(dlg)["custom"].setChecked(True)
    dlg._working_colors["primary"] = "#abcdef"
    dlg._on_apply()

    assert custom_theme_file.exists()
    assert get_theme_manager().mode == "custom"

    import json

    payload = json.loads(custom_theme_file.read_text())
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


def test_typography_scale_persists_to_settings(app, reset_theme, custom_theme_file):
    """The slider value is saved to settings.typography_scale on Apply.
    The custom_theme.json keeps Dark's un-scaled typography — the runtime
    scale is the single source of truth across all modes."""
    from git_gui.presentation.theme import settings as s

    dlg = ThemeDialog()
    _radios(dlg)["custom"].setChecked(True)
    dlg._typo_slider.setValue(150)
    dlg._on_apply()

    assert s.load_settings()["typography_scale"] == 1.5

    import json

    payload = json.loads(custom_theme_file.read_text())
    from git_gui.presentation.theme.loader import load_builtin

    dark_body = load_builtin("dark").typography.body_medium.size
    assert payload["typography"]["body_medium"]["size"] == dark_body


def test_reopen_dialog_prefills_from_saved_file(app, reset_theme, custom_theme_file):
    dlg1 = ThemeDialog()
    _radios(dlg1)["custom"].setChecked(True)
    dlg1._working_colors["primary"] = "#123456"
    dlg1._typo_slider.setValue(120)
    dlg1._on_apply()

    dlg2 = ThemeDialog()
    assert dlg2._working_colors["primary"] == "#123456"
    assert dlg2._typo_slider.value() == 120


def test_resaving_a_custom_theme_with_baked_in_sizes_writes_unscaled_typography(
    app, reset_theme, custom_theme_file
):
    """Files saved before typography_scale existed hold scaled sizes, and
    the runtime scale would otherwise be applied on top of them."""
    import dataclasses
    import json

    from git_gui.presentation.theme.loader import load_builtin

    dark = load_builtin("dark")
    body = dark.typography.body_medium
    baked = dataclasses.replace(
        dark,
        typography=dataclasses.replace(
            dark.typography, body_medium=dataclasses.replace(body, size=body.size * 2)
        ),
    )
    _write_custom_theme(custom_theme_file, baked)
    dlg = ThemeDialog()
    _radios(dlg)["custom"].setChecked(True)

    dlg._on_apply()

    payload = json.loads(custom_theme_file.read_text(encoding="utf-8"))
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


def test_dialog_opens_when_the_saved_custom_theme_is_malformed(app, reset_theme, custom_theme_file):
    """Outside Custom mode the app still launches, but the dialog read the
    broken file on open and raised, so View > Appearance did nothing."""
    custom_theme_file.write_text("{", encoding="utf-8")
    get_theme_manager().set_mode("dark")

    assert isinstance(ThemeDialog(), QDialog)


def _save_light_based_custom_theme_then_switch_to_dark() -> None:
    get_theme_manager().set_mode("light")
    dlg = ThemeDialog()
    _radios(dlg)["custom"].setChecked(True)
    dlg._on_apply()
    get_theme_manager().set_mode("dark")


def test_reapplying_a_saved_custom_theme_keeps_the_tokens_it_has_no_swatch_for(
    app, reset_theme, custom_theme_file
):
    """The swatches showed the saved file, but syntax colours and is_dark
    were saved from the active builtin: Light surfaces under Dark's pale
    syntax colours, with no swatch to repair them."""
    import json

    from git_gui.presentation.theme.loader import load_builtin

    _save_light_based_custom_theme_then_switch_to_dark()
    dlg = ThemeDialog()
    _radios(dlg)["custom"].setChecked(True)
    dlg._on_apply()

    payload = json.loads(custom_theme_file.read_text(encoding="utf-8"))
    assert payload["colors"]["syntax_string"] == load_builtin("light").colors.syntax_string
    assert payload["is_dark"] is False


def test_reset_takes_the_unswatched_tokens_back_to_the_active_theme_too(
    app, reset_theme, custom_theme_file
):
    import json

    from git_gui.presentation.theme.loader import load_builtin

    _save_light_based_custom_theme_then_switch_to_dark()
    dlg = ThemeDialog()
    _radios(dlg)["custom"].setChecked(True)
    dlg._on_reset()
    dlg._on_apply()

    payload = json.loads(custom_theme_file.read_text(encoding="utf-8"))
    assert payload["colors"]["syntax_string"] == load_builtin("dark").colors.syntax_string


def test_apply_tells_the_user_when_the_settings_cannot_be_saved(
    app, reset_theme, tmp_path, monkeypatch
):
    """The OSError used to escape the slot into the log only, so Apply
    looked as if it did nothing."""
    from PySide6.QtWidgets import QMessageBox

    from git_gui.presentation.theme import settings as s

    # On Dark before the path breaks: set_mode saves on a change, and
    # reset_theme's set_mode("dark") runs before monkeypatch is undone, so it
    # must find nothing to change. Apply is then the one save that fails.
    get_theme_manager().set_mode("dark")
    not_a_directory = tmp_path / "file"
    not_a_directory.write_text("", encoding="utf-8")
    monkeypatch.setattr(s, "settings_path", lambda: not_a_directory / "settings.json")
    warnings: list[tuple] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
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


@pytest.mark.parametrize("saved_before", [True, False], ids=["custom-saved", "none-saved"])
def test_settings_that_cannot_be_saved_leave_the_custom_theme_as_it_was(
    app, reset_theme, custom_theme_file, monkeypatch, saved_before
):
    """The custom file was written before settings.json, so Apply reported a
    failure and kept the old colours on screen, yet the next launch showed
    the new ones."""
    from PySide6.QtWidgets import QMessageBox

    from git_gui.presentation.theme import manager

    if saved_before:
        first = ThemeDialog()
        _radios(first)["custom"].setChecked(True)
        first._working_colors["primary"] = "#1f3e61"
        first._on_apply()
    before = custom_theme_file.read_bytes() if saved_before else None
    dlg = ThemeDialog()
    _radios(dlg)["custom"].setChecked(True)
    dlg._working_colors["primary"] = "#ff0000"

    def settings_held_open(_data) -> None:
        raise PermissionError(13, "Permission denied", "settings.json")

    warnings: list[tuple] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))

    with monkeypatch.context() as held:
        held.setattr(manager, "save_settings", settings_held_open)
        dlg._on_apply()

    assert warnings
    assert (custom_theme_file.read_bytes() if custom_theme_file.exists() else None) == before


def _write_custom_theme_with_lanes(custom_path: Path, lanes: int) -> None:
    import dataclasses

    from git_gui.presentation.theme.loader import load_builtin

    dark = load_builtin("dark")
    lane_colors = [f"#1234{i:02x}" for i in range(lanes)]
    theme = dataclasses.replace(
        dark, colors=dataclasses.replace(dark.colors, graph_lane_colors=lane_colors)
    )
    _write_custom_theme(custom_path, theme)


@pytest.mark.parametrize(
    ("saved_lanes", "active_mode", "radios_clicked"),
    [
        (1, "dark", ["custom"]),
        (10, "custom", ["light", "custom"]),
        (1, "custom", ["dark", "custom"]),
    ],
    ids=[
        "fewer-lanes-than-the-active-theme",
        "more-lanes-than-the-builtin-picked",
        "fewer-lanes-than-the-builtin-picked",
    ],
)
def test_the_lane_swatches_shown_are_the_lanes_apply_saves(
    app,
    reset_theme,
    qtbot,
    custom_theme_file,
    monkeypatch,
    saved_lanes,
    active_mode,
    radios_clicked,
):
    """The lane buttons were made once, for the theme active on open: a
    working theme with fewer lanes left stale swatches whose click raised
    IndexError, and one with more lanes had swatches missing."""
    import json

    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QColorDialog, QPushButton

    _write_custom_theme_with_lanes(custom_theme_file, saved_lanes)
    get_theme_manager().set_mode(active_mode)
    dlg = ThemeDialog()
    qtbot.addWidget(dlg)
    for mode in radios_clicked:
        _radios(dlg)[mode].setChecked(True)

    def lane_swatches() -> list[QPushButton]:
        return [
            b for b in dlg.findChildren(QPushButton) if b.accessibleName().startswith("Graph lane")
        ]

    assert [b.accessibleName() for b in lane_swatches()] == [
        f"Graph lane {i} colour {hex_value}" for i, hex_value in enumerate(dlg._working_lane_colors)
    ]
    monkeypatch.setattr(QColorDialog, "getColor", lambda *args, **kwargs: QColor("#abcdef"))
    with qtbot.capture_exceptions() as raised:
        for swatch in lane_swatches():
            swatch.click()
    assert raised == []
    dlg._on_apply()
    saved = json.loads(custom_theme_file.read_text(encoding="utf-8"))["colors"]["graph_lane_colors"]
    assert saved == ["#abcdef"] * len(lane_swatches())


def test_swatch_borders_take_the_themes_outline_colour(app, reset_theme):
    get_theme_manager().set_mode("light")
    dlg = ThemeDialog()

    outline = get_theme_manager().current.colors.outline
    assert f"border: 1px solid {outline}" in dlg._swatch_buttons["primary"].styleSheet()
    assert f"border: 1px solid {outline}" in dlg._lane_buttons[0].styleSheet()
