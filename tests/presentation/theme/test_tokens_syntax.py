from __future__ import annotations
import pytest

from git_gui.presentation.theme.loader import load_builtin


SYNTAX_ROLES = [
    "syntax_keyword",
    "syntax_function",
    "syntax_class",
    "syntax_string",
    "syntax_number",
    "syntax_comment",
    "syntax_operator",
    "syntax_decorator",
    "diff_added_word_overlay",
    "diff_removed_word_overlay",
]


@pytest.mark.parametrize("theme_name", ["light", "dark"])
@pytest.mark.parametrize("role", SYNTAX_ROLES)
def test_role_present_on_theme(theme_name, role):
    theme = load_builtin(theme_name)
    value = getattr(theme.colors, role)
    assert isinstance(value, str)
    assert value.startswith("#")  # hex color
    # Acceptable hex lengths: #RGB, #RRGGBB, #AARRGGBB
    assert len(value) in (4, 7, 9)


@pytest.mark.parametrize("theme_name", ["light", "dark"])
def test_word_overlay_differs_from_line_overlay(theme_name):
    """The word-level overlay must be visually distinct from the line overlay."""
    theme = load_builtin(theme_name)
    assert theme.colors.diff_added_word_overlay != theme.colors.diff_added_overlay
    assert theme.colors.diff_removed_word_overlay != theme.colors.diff_removed_overlay
