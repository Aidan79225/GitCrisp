from pathlib import Path

import pytest

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


@pytest.fixture
def settings_file(tmp_path, monkeypatch) -> Path:
    """Where settings.json is read from for this test (not yet written)."""
    path = tmp_path / "settings.json"
    monkeypatch.setattr(s, "settings_path", lambda: path)
    return path


def _write_text_scale(path: Path, json_value: str) -> None:
    """Write settings.json the way a user editing it by hand might: the value
    is raw JSON text, since NaN and Infinity are only reachable that way."""
    path.write_text(f'{{"typography_scale": {json_value}}}', encoding="utf-8")


def test_the_text_scale_is_one_when_no_settings_file_exists(settings_file):
    assert s.load_typography_scale() == 1.0


def test_the_text_scale_is_one_when_the_file_does_not_mention_it(settings_file):
    settings_file.write_text('{"theme_mode": "dark"}', encoding="utf-8")

    assert s.load_typography_scale() == 1.0


@pytest.mark.parametrize(
    ("json_value", "expected"),
    [("0.5", 0.5), ("0.75", 0.75), ("1", 1.0), ("1.5", 1.5), ("2", 2.0), ('"1.5"', 1.5)],
    ids=["minimum", "below-one", "integer", "above-one", "maximum", "numeric-string"],
)
def test_a_text_scale_within_the_range_is_returned_as_saved(settings_file, json_value, expected):
    _write_text_scale(settings_file, json_value)

    assert s.load_typography_scale() == expected


@pytest.mark.parametrize(
    "json_value",
    [
        '"large"',
        '"150%"',
        '""',
        "null",
        "[1.5]",
        '{"scale": 1.5}',
        "true",
        "false",
        "NaN",
        "Infinity",
        "-Infinity",
        "1e999",
        "1" + "0" * 400,
    ],
    ids=[
        "word",
        "percent-sign",
        "empty-string",
        "null",
        "list",
        "object",
        "true",
        "false",
        "nan",
        "infinity",
        "negative-infinity",
        "float-literal-beyond-float",
        "integer-beyond-float",
    ],
)
def test_a_text_scale_that_is_not_a_finite_number_falls_back_to_one_with_a_warning(
    settings_file, caplog, json_value
):
    _write_text_scale(settings_file, json_value)

    with caplog.at_level("WARNING"):
        scale = s.load_typography_scale()

    assert scale == 1.0
    assert any("typography_scale" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(
    ("json_value", "expected"),
    [("0.49", 0.5), ("0", 0.5), ("-3", 0.5), ("2.01", 2.0), ("150", 2.0), ("1e300", 2.0)],
    ids=["just-below", "zero", "negative", "just-above", "percent-by-mistake", "enormous"],
)
def test_a_text_scale_outside_the_range_is_limited_to_it(settings_file, json_value, expected):
    _write_text_scale(settings_file, json_value)

    assert s.load_typography_scale() == expected
