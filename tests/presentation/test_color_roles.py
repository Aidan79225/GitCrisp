"""ColorRole mirrors the Colors dataclass, and nothing lets them drift.

`Colors` stays where a theme defines its values; `ColorRole` is the vocabulary
a widget asks with. Two lists of the same names is a duplication worth having
only as long as something fails when they disagree — that is this file.
"""

from __future__ import annotations

import dataclasses

import pytest

from git_gui.domain.entities import FileDelta, StagingState
from git_gui.presentation.theme import ColorRole
from git_gui.presentation.theme.tokens import Colors


def _single_colour_fields() -> set[str]:
    return {f.name for f in dataclasses.fields(Colors) if f.type == "str"}


def test_every_colour_token_has_a_role():
    assert _single_colour_fields() - {str(role) for role in ColorRole} == set()


def test_every_role_names_a_real_token():
    assert {str(role) for role in ColorRole} - _single_colour_fields() == set()


def test_a_role_resolves_to_a_colour(theme_colors):
    assert theme_colors.as_qcolor(ColorRole.ON_SURFACE).isValid()


def test_an_unknown_token_still_raises(theme_colors):
    """as_qcolor is typed, but a wrong value must not silently paint nothing."""
    with pytest.raises(KeyError):
        theme_colors.as_qcolor("not_a_token")


def test_the_multi_colour_token_is_not_a_role():
    """graph_lane_colors is a list, so it can never answer as_qcolor."""
    assert "graph_lane_colors" not in {str(role) for role in ColorRole}


def test_every_badge_kind_resolves_to_a_status_colour(theme_colors):
    for kind in (*FileDelta, StagingState.CONFLICTED):
        assert theme_colors.status_color(kind).isValid()


def test_an_unmapped_badge_kind_falls_back_to_unknown(theme_colors):
    assert theme_colors.status_color("not-a-delta") == theme_colors.as_qcolor(
        ColorRole.STATUS_UNKNOWN
    )


@pytest.fixture
def theme_colors():
    from git_gui.presentation.theme import get_theme_manager

    return get_theme_manager().current.colors
