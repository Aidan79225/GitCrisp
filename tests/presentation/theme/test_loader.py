import json
import pytest
from pathlib import Path
from git_gui.presentation.theme.loader import (
    load_theme, load_builtin, ThemeValidationError,
)


def _valid_dict() -> dict:
    return {
        "name": "Test",
        "is_dark": False,
        "colors": {
            "primary": "#6750a4", "on_primary": "#ffffff",
            "primary_container": "#eaddff", "on_primary_container": "#21005d",
            "secondary": "#625b71", "on_secondary": "#ffffff",
            "error": "#b3261e", "on_error": "#ffffff",
            "surface": "#fffbfe", "on_surface": "#1c1b1f",
            "surface_variant": "#e7e0ec", "on_surface_variant": "#49454f",
            "surface_container": "#f3edf7", "surface_container_high": "#ece6f0",
            "outline": "#79747e", "outline_variant": "#cac4d0",
            "background": "#fffbfe", "on_background": "#1c1b1f",
            "diff_added_bg": "#d4f4dd", "diff_added_fg": "#0a3d1a",
            "diff_removed_bg": "#fbe2e2", "diff_removed_fg": "#5a0a0a",
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
        },
        "typography": {
            "title_large":  {"family": "X", "size": 22, "weight": 500, "letter_spacing": 0.0},
            "title_medium": {"family": "X", "size": 16, "weight": 500, "letter_spacing": 0.15},
            "body_large":   {"family": "X", "size": 14, "weight": 400, "letter_spacing": 0.5},
            "body_medium":  {"family": "X", "size": 13, "weight": 400, "letter_spacing": 0.0},
            "body_small":   {"family": "X", "size": 12, "weight": 400, "letter_spacing": 0.4},
            "label_large":  {"family": "X", "size": 14, "weight": 500, "letter_spacing": 0.1},
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
