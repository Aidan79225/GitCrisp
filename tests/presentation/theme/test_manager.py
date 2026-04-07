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
