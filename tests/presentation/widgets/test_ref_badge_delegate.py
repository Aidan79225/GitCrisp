"""Which colour a ref badge gets.

A local branch may have a slash in its name (``feature/login``) just as a
remote-tracking one does (``origin/main``), so the name alone cannot say which
it is; the caller has to.
"""

from __future__ import annotations

from PySide6.QtGui import QColor

from git_gui.presentation.theme import ColorRole, get_theme_manager
from git_gui.presentation.widgets.ref_badge_delegate import _badge_color

REMOTES = frozenset({"origin/main", "origin/feature/login"})


def _role(role: ColorRole) -> QColor:
    return get_theme_manager().current.colors.as_qcolor(role)


def test_a_local_branch_with_a_slash_gets_the_local_colour():
    assert _badge_color("feature/login", None, REMOTES) == _role(ColorRole.REF_BADGE_BRANCH_BG)


def test_a_remote_tracking_branch_gets_the_remote_colour():
    assert _badge_color("origin/main", None, REMOTES) == _role(ColorRole.REF_BADGE_REMOTE_BG)


def test_a_local_branch_without_a_slash_stays_local():
    assert _badge_color("main", None, REMOTES) == _role(ColorRole.REF_BADGE_BRANCH_BG)


def test_the_checked_out_branch_is_head_coloured_even_with_a_slash():
    colour = _badge_color("feature/login", "feature/login", REMOTES)

    assert colour == _role(ColorRole.BRANCH_HEAD_BG)


def test_a_tag_is_tag_coloured_whatever_its_name():
    assert _badge_color("tag:release/1.0", None, REMOTES) == _role(ColorRole.REF_BADGE_TAG_BG)
