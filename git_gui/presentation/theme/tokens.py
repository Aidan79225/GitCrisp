from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtGui import QColor, QFont

from git_gui.domain.entities import FileDelta, StagingState


class ColorRole(StrEnum):
    """Every single-colour token a widget can ask the palette for.

    Mirrors the fields of `Colors`, which stays where a theme defines its
    values; `test_color_roles.py` fails if the two drift apart. It exists
    because `as_qcolor` raises on a name it does not know, and its callers are
    `paint()` methods — a mistyped token there is not a wrong colour, it is a
    view that stops drawing.
    """

    PRIMARY = "primary"
    ON_PRIMARY = "on_primary"
    PRIMARY_CONTAINER = "primary_container"
    ON_PRIMARY_CONTAINER = "on_primary_container"
    SECONDARY = "secondary"
    ON_SECONDARY = "on_secondary"
    ERROR = "error"
    ON_ERROR = "on_error"
    SURFACE = "surface"
    ON_SURFACE = "on_surface"
    SURFACE_VARIANT = "surface_variant"
    ON_SURFACE_VARIANT = "on_surface_variant"
    SURFACE_CONTAINER = "surface_container"
    SURFACE_CONTAINER_HIGH = "surface_container_high"
    OUTLINE = "outline"
    OUTLINE_VARIANT = "outline_variant"
    BACKGROUND = "background"
    ON_BACKGROUND = "on_background"
    DIFF_ADDED_BG = "diff_added_bg"
    DIFF_ADDED_FG = "diff_added_fg"
    DIFF_REMOVED_BG = "diff_removed_bg"
    DIFF_REMOVED_FG = "diff_removed_fg"
    REF_BADGE_BRANCH_BG = "ref_badge_branch_bg"
    REF_BADGE_TAG_BG = "ref_badge_tag_bg"
    REF_BADGE_REMOTE_BG = "ref_badge_remote_bg"
    STATUS_MODIFIED = "status_modified"
    STATUS_ADDED = "status_added"
    STATUS_DELETED = "status_deleted"
    STATUS_RENAMED = "status_renamed"
    STATUS_UNKNOWN = "status_unknown"
    STATUS_CONFLICTED = "status_conflicted"
    BRANCH_HEAD_BG = "branch_head_bg"
    DIFF_FILE_HEADER_FG = "diff_file_header_fg"
    DIFF_HUNK_HEADER_FG = "diff_hunk_header_fg"
    DIFF_ADDED_OVERLAY = "diff_added_overlay"
    DIFF_REMOVED_OVERLAY = "diff_removed_overlay"
    ON_BADGE = "on_badge"
    HOVER_OVERLAY = "hover_overlay"
    SYNTAX_KEYWORD = "syntax_keyword"
    SYNTAX_FUNCTION = "syntax_function"
    SYNTAX_CLASS = "syntax_class"
    SYNTAX_STRING = "syntax_string"
    SYNTAX_NUMBER = "syntax_number"
    SYNTAX_COMMENT = "syntax_comment"
    SYNTAX_OPERATOR = "syntax_operator"
    SYNTAX_DECORATOR = "syntax_decorator"
    DIFF_ADDED_WORD_OVERLAY = "diff_added_word_overlay"
    DIFF_REMOVED_WORD_OVERLAY = "diff_removed_word_overlay"


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
    graph_lane_colors: list[str]
    ref_badge_branch_bg: str
    ref_badge_tag_bg: str
    ref_badge_remote_bg: str
    # Status colors (working tree / diff badges)
    status_modified: str
    status_added: str
    status_deleted: str
    status_renamed: str
    status_unknown: str
    status_conflicted: str
    # Branch
    branch_head_bg: str
    # Diff accents
    diff_file_header_fg: str
    diff_hunk_header_fg: str
    diff_added_overlay: str
    diff_removed_overlay: str
    # Misc
    on_badge: str
    hover_overlay: str
    # Syntax highlighting (Pygments token roles)
    syntax_keyword: str
    syntax_function: str
    syntax_class: str
    syntax_string: str
    syntax_number: str
    syntax_comment: str
    syntax_operator: str
    syntax_decorator: str
    # Word-level diff overlays (layered over line overlays)
    diff_added_word_overlay: str
    diff_removed_word_overlay: str

    def as_qcolor(self, role: ColorRole) -> QColor:
        value = getattr(self, role, None)
        if not isinstance(value, str):
            raise KeyError(f"Unknown color token: {role}")
        return QColor(value)

    def status_color(self, kind: FileDelta | StagingState) -> QColor:
        """The badge colour for a delta — or for a conflict, which outranks it."""
        try:
            role = ColorRole(f"status_{kind}")
        except ValueError:
            role = ColorRole.STATUS_UNKNOWN
        return self.as_qcolor(role)


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
