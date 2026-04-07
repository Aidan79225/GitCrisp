from pathlib import Path
from git_gui.presentation.theme import settings as s


def test_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "settings_path", lambda: tmp_path / "settings.json")
    s.save_settings({"theme_mode": "dark"})
    assert s.load_settings() == {"theme_mode": "dark"}


def test_missing_file_returns_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "settings_path", lambda: tmp_path / "missing.json")
    assert s.load_settings() == {"theme_mode": "system"}


def test_malformed_file_returns_defaults(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    p.write_text("{not json")
    monkeypatch.setattr(s, "settings_path", lambda: p)
    assert s.load_settings() == {"theme_mode": "system"}
