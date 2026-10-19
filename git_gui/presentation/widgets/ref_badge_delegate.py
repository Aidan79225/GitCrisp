from __future__ import annotations

from PySide6.QtGui import QColor

from git_gui.presentation.theme import ColorRole, get_theme_manager

BADGE_RADIUS = 4  # rounded corner radius
BADGE_H_PAD = 4  # horizontal padding inside badge
BADGE_V_PAD = 2  # vertical padding inside badge
BADGE_GAP = 4  # gap between consecutive badges, and after last badge


def _color_head() -> QColor:
    return get_theme_manager().current.colors.as_qcolor(ColorRole.BRANCH_HEAD_BG)


def _color_local() -> QColor:
    return get_theme_manager().current.colors.as_qcolor(ColorRole.REF_BADGE_BRANCH_BG)


def _color_remote() -> QColor:
    return get_theme_manager().current.colors.as_qcolor(ColorRole.REF_BADGE_REMOTE_BG)


def _color_tag() -> QColor:
    return get_theme_manager().current.colors.as_qcolor(ColorRole.REF_BADGE_TAG_BG)


def _badge_color(
    name: str,
    head_branch: str | None = None,
    remote_branches: frozenset[str] = frozenset(),
) -> QColor:
    """The badge colour for ref `name`.

    Remote-tracking branches are the ones in `remote_branches`: a local branch
    can hold a slash (``feature/login``) just as ``origin/main`` does.
    """
    if name == "HEAD":
        return _color_head()
    if head_branch and name == head_branch:
        return _color_head()
    if name.startswith("tag:"):
        return _color_tag()
    if name in remote_branches:
        return _color_remote()
    return _color_local()


def _badge_display_name(name: str) -> str:
    """Strip 'tag:' prefix for display."""
    if name.startswith("tag:"):
        return name[4:]
    return name


def _badge_copy_text(name: str) -> str:
    """The ref name to place on the clipboard when a badge is clicked.

    That is the bare branch or tag name the badge shows, without the
    internal 'tag:' marker.
    """
    return _badge_display_name(name)
