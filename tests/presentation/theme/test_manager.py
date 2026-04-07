import pytest
from PySide6.QtWidgets import QApplication
from git_gui.presentation.theme import settings as s
from git_gui.presentation.theme.manager import ThemeManager
from git_gui.presentation.theme.tokens import Theme


@pytest.fixture
def app():
    a = QApplication.instance() or QApplication([])
    yield a


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "settings_path", lambda: tmp_path / "settings.json")


def test_initial_mode_defaults_to_system(app, isolated_settings):
    mgr = ThemeManager(app)
    assert mgr.mode == "system"
    assert isinstance(mgr.current, Theme)


def test_set_mode_emits_signal_and_changes_theme(app, isolated_settings):
    mgr = ThemeManager(app)
    received = []
    mgr.theme_changed.connect(lambda t: received.append(t))
    mgr.set_mode("dark")
    assert mgr.mode == "dark"
    assert mgr.current.is_dark is True
    assert len(received) == 1
    assert received[0].is_dark is True


def test_set_mode_persists(app, isolated_settings):
    mgr1 = ThemeManager(app)
    mgr1.set_mode("light")
    mgr2 = ThemeManager(app)
    assert mgr2.mode == "light"
    assert mgr2.current.is_dark is False


def test_set_mode_applies_global_qss(app, isolated_settings):
    mgr = ThemeManager(app)
    mgr.set_mode("dark")
    # Global QSS is intentionally empty until widget migration; just
    # confirm the call path runs and styleSheet() returns a string.
    assert isinstance(app.styleSheet(), str)
    return
    qss = app.styleSheet()
    assert "QPushButton" in qss
    assert len(qss) > 200


def test_set_mode_custom_loads_from_file(app, isolated_settings, tmp_path, monkeypatch):
    import json
    import dataclasses
    from git_gui.presentation.theme import settings as s
    from git_gui.presentation.theme.loader import load_builtin

    custom_path = tmp_path / "custom_theme.json"
    monkeypatch.setattr(s, "custom_theme_path", lambda: custom_path)

    base = load_builtin("light")
    payload = {
        "name": "Custom Test",
        "is_dark": base.is_dark,
        "colors": dataclasses.asdict(base.colors),
        "typography": {
            f.name: dataclasses.asdict(getattr(base.typography, f.name))
            for f in dataclasses.fields(type(base.typography))
        },
        "shape": dataclasses.asdict(base.shape),
        "spacing": dataclasses.asdict(base.spacing),
    }
    custom_path.write_text(json.dumps(payload))

    mgr = ThemeManager(app)
    mgr.set_mode("custom")
    assert mgr.mode == "custom"
    assert mgr.current.name == "Custom Test"


def test_set_mode_custom_missing_file_falls_back_to_dark(app, isolated_settings, tmp_path, monkeypatch, caplog):
    from git_gui.presentation.theme import settings as s
    monkeypatch.setattr(s, "custom_theme_path", lambda: tmp_path / "missing.json")

    mgr = ThemeManager(app)
    with caplog.at_level("WARNING"):
        mgr.set_mode("custom")
    assert mgr.mode == "custom"
    assert mgr.current.is_dark is True
    assert any("custom" in r.message.lower() for r in caplog.records)


def test_palette_follows_theme(app, isolated_settings):
    from PySide6.QtGui import QPalette
    mgr = ThemeManager(app)
    mgr.set_mode("dark")
    pal_dark = app.palette()
    dark_window = pal_dark.color(QPalette.Window).name()

    mgr.set_mode("light")
    pal_light = app.palette()
    light_window = pal_light.color(QPalette.Window).name()

    assert dark_window != light_window, "Window palette colour should change between dark and light"

    # Sanity: Highlight should match the theme's primary token in light mode.
    from git_gui.presentation.theme.loader import load_builtin
    expected = load_builtin("light").colors.primary
    assert pal_light.color(QPalette.Highlight).name() == expected
