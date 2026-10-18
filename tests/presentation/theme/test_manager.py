import pytest
from PySide6.QtWidgets import QApplication

from git_gui.presentation.theme import settings as s
from git_gui.presentation.theme.loader import load_builtin
from git_gui.presentation.theme.manager import ThemeManager
from git_gui.presentation.theme.qss_template import render
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
    dark_qss = app.styleSheet()
    mgr.set_mode("light")
    light_qss = app.styleSheet()

    assert dark_qss == render(load_builtin("dark"))
    assert light_qss == render(load_builtin("light"))


def test_set_mode_custom_loads_from_file(app, isolated_settings, tmp_path, monkeypatch):
    import dataclasses
    import json

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


def test_set_mode_custom_missing_file_falls_back_to_dark(
    app, isolated_settings, tmp_path, monkeypatch, caplog
):
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
        unscaled = max(1, round(body.size * 1.0))
        assert app.font().pointSize() > unscaled


def test_a_malformed_custom_theme_falls_back_to_dark_at_launch(
    app, isolated_settings, tmp_path, monkeypatch
):
    """A Custom file cut short by a crash during Apply used to raise out of
    ThemeManager.__init__, so the app never opened again."""
    from git_gui.presentation.theme.loader import load_builtin

    custom_path = tmp_path / "custom_theme.json"
    custom_path.write_text('{"name": "Cust', encoding="utf-8")
    monkeypatch.setattr(s, "custom_theme_path", lambda: custom_path)
    s.save_settings({"theme_mode": "custom"})

    mgr = ThemeManager(app)

    assert mgr.current.name == load_builtin("dark").name


def test_a_settings_write_that_fails_leaves_the_mode_as_it_was(
    app, isolated_settings, tmp_path, monkeypatch
):
    """The mode used to change before the write, so a read-only settings
    file left mgr.mode saying Light while Dark stayed on screen."""
    mgr = ThemeManager(app)
    mgr.set_mode("dark")
    not_a_directory = tmp_path / "file"
    not_a_directory.write_text("", encoding="utf-8")
    monkeypatch.setattr(s, "settings_path", lambda: not_a_directory / "settings.json")

    with pytest.raises(OSError):
        mgr.set_mode("light")

    assert mgr.mode == "dark"


@pytest.fixture
def restore_app_font(app):
    from PySide6.QtGui import QFont

    original = QFont(app.font())
    yield
    app.setFont(original)


def _shown_in_a_window(widget):
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    window = QWidget()
    QVBoxLayout(window).addWidget(widget)
    window.show()
    return window


def test_a_theme_change_keeps_the_font_family_a_widget_chose(
    app, isolated_settings, restore_app_font
):
    """The commit message and the Operations Log set Courier New, and every
    Apply replaced it with the proportional UI font until restart."""
    from PySide6.QtWidgets import QPlainTextEdit

    mgr = ThemeManager(app)
    mono = QPlainTextEdit()
    font = mono.font()
    font.setFamily("Courier New")
    mono.setFont(font)
    _window = _shown_in_a_window(mono)

    mgr.set_mode("light", force=True)

    assert mono.font().family() == "Courier New"


def test_a_theme_change_keeps_the_bold_a_widget_chose(app, isolated_settings, restore_app_font):
    from PySide6.QtWidgets import QLabel

    mgr = ThemeManager(app)
    title = QLabel("REPOSITORIES")
    font = title.font()
    font.setBold(True)
    title.setFont(font)
    _window = _shown_in_a_window(title)

    mgr.set_mode("light", force=True)

    assert title.font().bold()


def test_a_widget_without_its_own_font_follows_the_typography_scale(
    app, isolated_settings, restore_app_font
):
    """Under an application style sheet Qt does not pass a new application
    font down to child widgets itself, so the manager still has to."""
    from PySide6.QtWidgets import QLabel

    mgr = ThemeManager(app)
    label = QLabel("plain")
    _window = _shown_in_a_window(label)
    s.save_settings({"typography_scale": 2.0})

    mgr.set_mode("light", force=True)

    assert label.font().pointSize() == app.font().pointSize()


def test_a_new_text_scale_is_shown_even_when_the_mode_is_unchanged(
    app, isolated_settings, restore_app_font
):
    """Apply in the Appearance dialog often keeps the mode and changes only
    the scale, which must still reach the screen."""
    mgr = ThemeManager(app)
    mgr.set_mode("light")
    unscaled = app.font().pointSize()

    mgr.set_appearance("light", 2.0)

    assert app.font().pointSize() > unscaled
    assert s.load_settings()["typography_scale"] == 2.0
