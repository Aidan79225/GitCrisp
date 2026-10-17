import json
from pathlib import Path

import pytest

from git_gui.presentation.theme.loader import (
    ThemeValidationError,
    load_builtin,
    load_theme,
)


def _valid_dict() -> dict:
    return {
        "name": "Test",
        "is_dark": False,
        "colors": {
            "primary": "#6750a4",
            "on_primary": "#ffffff",
            "primary_container": "#eaddff",
            "on_primary_container": "#21005d",
            "secondary": "#625b71",
            "on_secondary": "#ffffff",
            "error": "#b3261e",
            "on_error": "#ffffff",
            "surface": "#fffbfe",
            "on_surface": "#1c1b1f",
            "surface_variant": "#e7e0ec",
            "on_surface_variant": "#49454f",
            "surface_container": "#f3edf7",
            "surface_container_high": "#ece6f0",
            "outline": "#79747e",
            "outline_variant": "#cac4d0",
            "background": "#fffbfe",
            "on_background": "#1c1b1f",
            "diff_added_bg": "#d4f4dd",
            "diff_added_fg": "#0a3d1a",
            "diff_removed_bg": "#fbe2e2",
            "diff_removed_fg": "#5a0a0a",
            "graph_lane_colors": ["#1976d2", "#388e3c"],
            "ref_badge_branch_bg": "#1976d2",
            "ref_badge_tag_bg": "#fbc02d",
            "ref_badge_remote_bg": "#7b1fa2",
            "status_modified": "#1f6feb",
            "status_added": "#238636",
            "status_deleted": "#da3633",
            "status_renamed": "#f0883e",
            "status_unknown": "#8b949e",
            "status_conflicted": "#f85149",
            "branch_head_bg": "#238636",
            "diff_file_header_fg": "#9a6700",
            "diff_hunk_header_fg": "#0969da",
            "diff_added_overlay": "#23863650",
            "diff_removed_overlay": "#f8514950",
            "on_badge": "#ffffff",
            "hover_overlay": "#0000001e",
            "syntax_keyword": "#cf222e",
            "syntax_function": "#8250df",
            "syntax_class": "#953800",
            "syntax_string": "#0a3069",
            "syntax_number": "#0550ae",
            "syntax_comment": "#6e7781",
            "syntax_operator": "#cf222e",
            "syntax_decorator": "#8250df",
            "diff_added_word_overlay": "#80aceebb",
            "diff_removed_word_overlay": "#80ffcecb",
        },
        "typography": {
            "title_large": {"family": "X", "size": 22, "weight": 500, "letter_spacing": 0.0},
            "title_medium": {"family": "X", "size": 16, "weight": 500, "letter_spacing": 0.15},
            "body_large": {"family": "X", "size": 14, "weight": 400, "letter_spacing": 0.5},
            "body_medium": {"family": "X", "size": 13, "weight": 400, "letter_spacing": 0.0},
            "body_small": {"family": "X", "size": 12, "weight": 400, "letter_spacing": 0.4},
            "label_large": {"family": "X", "size": 14, "weight": 500, "letter_spacing": 0.1},
            "label_medium": {"family": "X", "size": 12, "weight": 500, "letter_spacing": 0.5},
        },
        "shape": {"corner_xs": 4, "corner_sm": 8, "corner_md": 12, "corner_lg": 16},
        "spacing": {"xs": 4, "sm": 8, "md": 16, "lg": 24, "xl": 32},
    }


def _write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "theme.json"
    p.write_text(json.dumps(data))
    return p


def test_load_valid(tmp_path):
    t = load_theme(_write(tmp_path, _valid_dict()))
    assert t.name == "Test"
    assert t.colors.primary == "#6750a4"
    assert t.typography.body_medium.size == 13


def test_load_missing_required_key(tmp_path):
    d = _valid_dict()
    del d["colors"]["primary"]
    with pytest.raises(ThemeValidationError, match="primary"):
        load_theme(_write(tmp_path, d))


def test_load_unknown_key(tmp_path):
    d = _valid_dict()
    d["colors"]["bogus"] = "#000000"
    with pytest.raises(ThemeValidationError, match="bogus"):
        load_theme(_write(tmp_path, d))


def test_load_bad_hex(tmp_path):
    d = _valid_dict()
    d["colors"]["primary"] = "not-a-color"
    with pytest.raises(ThemeValidationError, match="primary"):
        load_theme(_write(tmp_path, d))


def test_load_builtin_light():
    t = load_builtin("light")
    assert t.is_dark is False
    assert t.name


def test_load_builtin_dark():
    t = load_builtin("dark")
    assert t.is_dark is True


@pytest.mark.parametrize(
    "content",
    [b"", b'{"name": "Cust', b"\xff\xfe{}"],
    ids=["empty", "truncated", "not-utf8"],
)
def test_a_file_that_is_not_json_is_a_validation_error(tmp_path, content):
    """Callers fall back to Dark on ThemeValidationError; anything else
    escaped them and stopped the app from launching."""
    p = tmp_path / "theme.json"
    p.write_bytes(content)
    with pytest.raises(ThemeValidationError):
        load_theme(p)


def test_a_theme_saved_with_a_byte_order_mark_loads(tmp_path):
    """Windows editors save UTF-8 with a BOM, which plain utf-8 rejects."""
    p = tmp_path / "theme.json"
    p.write_text(json.dumps(_valid_dict()), encoding="utf-8-sig")
    assert load_theme(p).name == "Test"


def _with(path: str, value) -> dict:
    d = _valid_dict()
    *parents, leaf = path.split(".")
    target = d
    for key in parents:
        target = target[key]
    target[leaf] = value
    return d


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("name", 5),
        ("is_dark", "false"),
        ("colors", "#000000"),
        ("typography", []),
        ("typography.body_medium", "X"),
        ("typography.body_medium.family", 1),
        ("typography.body_medium.size", "10"),
        ("typography.body_medium.weight", True),
        ("typography.body_medium.letter_spacing", "0.5"),
        ("shape", None),
        ("shape.corner_xs", "4"),
        ("spacing.md", 16.5),
    ],
)
def test_a_value_of_the_wrong_type_is_a_validation_error(tmp_path, path, value):
    with pytest.raises(ThemeValidationError, match=path.split(".")[-1]):
        load_theme(_write(tmp_path, _with(path, value)))


def test_an_integer_letter_spacing_is_accepted(tmp_path):
    """JSON has one number type, so 0 and 0.0 are the same spacing."""
    t = load_theme(_write(tmp_path, _with("typography.body_medium.letter_spacing", 1)))
    assert t.typography.body_medium.letter_spacing == 1
