from git_gui.presentation.theme.tokens import (
    Theme, Colors, Typography, TextStyle, Shape, Spacing,
)
from PySide6.QtGui import QColor, QFont


def _minimal_theme(name="Test", is_dark=False) -> Theme:
    colors = Colors(
        primary="#6750a4", on_primary="#ffffff",
        primary_container="#eaddff", on_primary_container="#21005d",
        secondary="#625b71", on_secondary="#ffffff",
        error="#b3261e", on_error="#ffffff",
        surface="#fffbfe", on_surface="#1c1b1f",
        surface_variant="#e7e0ec", on_surface_variant="#49454f",
        surface_container="#f3edf7", surface_container_high="#ece6f0",
        outline="#79747e", outline_variant="#cac4d0",
        background="#fffbfe", on_background="#1c1b1f",
        diff_added_bg="#d4f4dd", diff_added_fg="#0a3d1a",
        diff_removed_bg="#fbe2e2", diff_removed_fg="#5a0a0a",
        graph_lane_colors=["#1976d2", "#388e3c", "#d32f2f", "#7b1fa2"],
        ref_badge_branch_bg="#1976d2",
        ref_badge_tag_bg="#fbc02d",
        ref_badge_remote_bg="#7b1fa2",
        status_modified="#1f6feb",
        status_added="#238636",
        status_deleted="#da3633",
        status_renamed="#f0883e",
        status_unknown="#8b949e",
        status_conflicted="#f85149",
        branch_head_bg="#238636",
        diff_file_header_fg="#e3b341",
        diff_hunk_header_fg="#58a6ff",
        diff_added_overlay="#23863650",
        diff_removed_overlay="#f8514950",
        on_badge="#ffffff",
        hover_overlay="#ffffff1e",
        syntax_keyword="#ff7b72",
        syntax_function="#d2a8ff",
        syntax_class="#f0c674",
        syntax_string="#a5d6ff",
        syntax_number="#79c0ff",
        syntax_comment="#8b949e",
        syntax_operator="#ff7b72",
        syntax_decorator="#d2a8ff",
        diff_added_word_overlay="#80238636",
        diff_removed_word_overlay="#80f85149",
    )
    body = TextStyle(family="SF Pro Text", size=13, weight=400, letter_spacing=0.0)
    typo = Typography(
        title_large=TextStyle("SF Pro Display", 22, 500, 0.0),
        title_medium=TextStyle("SF Pro Display", 16, 500, 0.15),
        body_large=TextStyle("SF Pro Text", 14, 400, 0.5),
        body_medium=body,
        body_small=TextStyle("SF Pro Text", 12, 400, 0.4),
        label_large=TextStyle("SF Pro Text", 14, 500, 0.1),
        label_medium=TextStyle("SF Pro Text", 12, 500, 0.5),
    )
    return Theme(
        name=name, is_dark=is_dark,
        colors=colors, typography=typo,
        shape=Shape(corner_xs=4, corner_sm=8, corner_md=12, corner_lg=16),
        spacing=Spacing(xs=4, sm=8, md=16, lg=24, xl=32),
    )


def test_theme_is_frozen():
    t = _minimal_theme()
    import dataclasses
    try:
        t.name = "Other"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("Theme should be frozen")


def test_colors_as_qcolor():
    t = _minimal_theme()
    qc = t.colors.as_qcolor("primary")
    assert isinstance(qc, QColor)
    assert qc.name() == "#6750a4"


def test_typography_as_qfont():
    t = _minimal_theme()
    qf = t.typography.as_qfont("body_medium")
    assert isinstance(qf, QFont)
    assert qf.pointSize() == 13
    assert qf.weight() == QFont.Weight.Normal or qf.weight() == 400


def test_unknown_color_raises():
    t = _minimal_theme()
    import pytest
    with pytest.raises(KeyError):
        t.colors.as_qcolor("nonexistent")
