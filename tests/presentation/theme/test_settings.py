from git_gui.presentation.theme import settings as s


def test_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "settings_path", lambda: tmp_path / "settings.json")
    s.save_settings({"theme_mode": "dark"})
    loaded = s.load_settings()
    assert loaded["theme_mode"] == "dark"
    # Missing keys are filled in from DEFAULTS on load.
    for k, v in s.DEFAULTS.items():
        if k != "theme_mode":
            assert loaded[k] == v


def test_missing_file_returns_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "settings_path", lambda: tmp_path / "missing.json")
    assert s.load_settings() == s.DEFAULTS


def test_malformed_file_returns_defaults(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    p.write_text("{not json")
    monkeypatch.setattr(s, "settings_path", lambda: p)
    assert s.load_settings() == s.DEFAULTS
