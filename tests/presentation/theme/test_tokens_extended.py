from git_gui.presentation.theme.tokens import Colors
from PySide6.QtGui import QColor


_NEW_TOKEN_NAMES = [
    "status_modified", "status_added", "status_deleted",
    "status_renamed", "status_unknown", "status_conflicted",
    "branch_head_bg",
    "diff_file_header_fg", "diff_hunk_header_fg",
    "diff_added_overlay", "diff_removed_overlay",
    "on_badge", "hover_overlay",
]


def _make_colors(**overrides):
    base = dict(
        primary="#264f78", on_primary="#ffffff",
        primary_container="#264f78", on_primary_container="#ffffff",
        secondary="#0d6efd", on_secondary="#ffffff",
        error="#f85149", on_error="#ffffff",
        surface="#252526", on_surface="#cccccc",
        surface_variant="#2a2d2e", on_surface_variant="#8b949e",
        surface_container="#1e1e1e", surface_container_high="#161b22",
        outline="#30363d", outline_variant="#30363d",
        background="#1e1e1e", on_background="#cccccc",
        diff_added_bg="#1d3a26", diff_added_fg="#ffffff",
        diff_removed_bg="#3e2025", diff_removed_fg="#ffffff",
        graph_lane_colors=["#4fc1ff"],
        ref_badge_branch_bg="#0d6efd",
        ref_badge_tag_bg="#a371f7",
        ref_badge_remote_bg="#1f4287",
        # New tokens
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
    base.update(overrides)
    return Colors(**base)


def test_all_new_tokens_exist():
    c = _make_colors()
    for name in _NEW_TOKEN_NAMES:
        assert hasattr(c, name), f"missing token {name}"


def test_status_color_lookup():
    c = _make_colors()
    assert c.status_color("modified").name() == "#1f6feb"
    assert c.status_color("added").name() == "#238636"
    assert c.status_color("deleted").name() == "#da3633"
    assert c.status_color("renamed").name() == "#f0883e"
    assert c.status_color("unknown").name() == "#8b949e"


def test_status_color_falls_back_to_unknown():
    c = _make_colors()
    assert c.status_color("nonexistent").name() == c.status_color("unknown").name()


def test_overlay_tokens_carry_alpha():
    c = _make_colors()
    qc = c.as_qcolor("diff_added_overlay")
    assert isinstance(qc, QColor)
    assert qc.alpha() < 255
