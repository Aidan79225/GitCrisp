from __future__ import annotations
from dataclasses import dataclass, field, fields
from typing import List
from PySide6.QtGui import QColor, QFont


@dataclass(frozen=True)
class Colors:
    primary: str
    on_primary: str
    primary_container: str
    on_primary_container: str
    secondary: str
    on_secondary: str
    error: str
    on_error: str
    surface: str
    on_surface: str
    surface_variant: str
    on_surface_variant: str
    surface_container: str
    surface_container_high: str
    outline: str
    outline_variant: str
    background: str
    on_background: str
    diff_added_bg: str
    diff_added_fg: str
    diff_removed_bg: str
    diff_removed_fg: str
    graph_lane_colors: List[str]
    ref_badge_branch_bg: str
    ref_badge_tag_bg: str
    ref_badge_remote_bg: str

    def as_qcolor(self, name: str) -> QColor:
        if not hasattr(self, name):
            raise KeyError(f"Unknown color token: {name}")
        value = getattr(self, name)
        if not isinstance(value, str):
            raise KeyError(f"Token {name} is not a single color")
        return QColor(value)


@dataclass(frozen=True)
class TextStyle:
    family: str
    size: int
    weight: int
    letter_spacing: float


@dataclass(frozen=True)
class Typography:
    title_large: TextStyle
    title_medium: TextStyle
    body_large: TextStyle
    body_medium: TextStyle
    body_small: TextStyle
    label_large: TextStyle
    label_medium: TextStyle

    def as_qfont(self, name: str) -> QFont:
        if not hasattr(self, name):
            raise KeyError(f"Unknown typography token: {name}")
        ts: TextStyle = getattr(self, name)
        f = QFont(ts.family, ts.size)
        f.setWeight(QFont.Weight(ts.weight))
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, ts.letter_spacing)
        return f


@dataclass(frozen=True)
class Shape:
    corner_xs: int
    corner_sm: int
    corner_md: int
    corner_lg: int


@dataclass(frozen=True)
class Spacing:
    xs: int
    sm: int
    md: int
    lg: int
    xl: int


@dataclass(frozen=True)
class Theme:
    name: str
    is_dark: bool
    colors: Colors
    typography: Typography
    shape: Shape
    spacing: Spacing
