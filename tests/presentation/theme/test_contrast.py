"""The text colour widgets draw on a theme colour.

Avatars put initials on the graph lane colours, and the Appearance dialog
labels each swatch with its hex value on the swatch's own colour.
"""

from __future__ import annotations

import dataclasses
import re

import pytest
from PySide6.QtGui import QColor

from git_gui.presentation.theme.contrast import readable_text_on
from git_gui.presentation.theme.loader import load_builtin

from .test_light_contrast import _ratio

_OPAQUE_HEX = re.compile(r"#[0-9a-fA-F]{6}")


def _opaque_colours(mode: str) -> list[str]:
    """Every #RRGGBB colour of a builtin theme, lanes included."""
    colors = load_builtin(mode).colors
    values = [*dataclasses.asdict(colors).values(), *colors.graph_lane_colors]
    return [v for v in values if isinstance(v, str) and _OPAQUE_HEX.fullmatch(v)]


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_text_meets_aa_contrast_on_every_theme_colour(mode):
    # Measured with the theme tests' own WCAG formula, not the one
    # readable_text_on chooses with, so a wrong luminance cannot pass.
    ratios = {
        fill: _ratio(readable_text_on(QColor(fill)).name(), fill) for fill in _opaque_colours(mode)
    }

    worst = min(ratios, key=ratios.__getitem__)

    assert ratios[worst] >= 4.5, f"{mode}: text on {worst} is {ratios[worst]:.2f}:1"


@pytest.mark.parametrize(
    ("fill", "text"), [("#fff9c4", "#000000"), ("#0d1b4c", "#ffffff")], ids=["pale", "deep"]
)
def test_text_is_dark_on_pale_fills_and_light_on_deep_ones(fill, text):
    assert readable_text_on(QColor(fill)).name() == text
