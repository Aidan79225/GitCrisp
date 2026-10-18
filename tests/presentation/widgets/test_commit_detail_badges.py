"""Which colour the commit header paints each ref badge.

A local branch can have a slash in its name (``feature/login``) just as
``origin/main`` does, so the header has to be told which branches are remote
and which one is checked out; the name alone cannot say.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtGui import QColor, QImage

from git_gui.domain.entities import Branch, Commit, FileStatus
from git_gui.presentation.theme import ColorRole, get_theme_manager
from git_gui.presentation.widgets.commit_detail import CommitDetailWidget
from git_gui.presentation.widgets.diff import DiffWidget
from git_gui.presentation.widgets.ref_badge_delegate import BADGE_H_PAD

OID = "a" * 40
COMMIT = Commit(
    oid=OID, message="m", author="A <a@example.com>", timestamp=datetime(2026, 1, 1), parents=[]
)


@pytest.fixture(autouse=True)
def _no_avatar_fetch():
    """Keep set_commit off the network; see test_commit_detail.py for the crash it causes."""
    from git_gui.presentation.widgets.avatar_loader import get_avatar_loader

    loader = get_avatar_loader()
    original = loader._enabled
    loader._enabled = False
    yield
    loader._enabled = original


def _role(role: ColorRole) -> int:
    return get_theme_manager().current.colors.as_qcolor(role).rgb()


def _painted_badge_colours(detail: CommitDetailWidget) -> dict[str, int]:
    """Render the header off screen and sample each badge's fill beside its text."""
    image = QImage(detail.size(), QImage.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    detail.render(image)
    badges = detail._layout(detail._commit, detail.fontMetrics()).badges
    return {
        badge.copy_text: image.pixelColor(
            badge.rect.left() + BADGE_H_PAD // 2, badge.rect.center().y()
        ).rgb()
        for badge in badges
    }


def test_a_local_branch_with_a_slash_is_painted_in_the_local_colour(qtbot):
    detail = CommitDetailWidget()
    qtbot.addWidget(detail)
    detail.resize(900, 120)
    detail.set_commit(
        COMMIT,
        ["feature/login", "origin/main"],
        remote_branches=frozenset({"origin/main"}),
    )

    colours = _painted_badge_colours(detail)

    assert colours["feature/login"] == _role(ColorRole.REF_BADGE_BRANCH_BG)
    assert colours["origin/main"] == _role(ColorRole.REF_BADGE_REMOTE_BG)


def test_the_checked_out_branch_is_painted_in_the_head_colour(qtbot):
    detail = CommitDetailWidget()
    qtbot.addWidget(detail)
    detail.resize(900, 120)
    detail.set_commit(COMMIT, ["feature/login"], head_branch="feature/login")

    colours = _painted_badge_colours(detail)

    assert colours["feature/login"] == _role(ColorRole.BRANCH_HEAD_BG)


def test_the_commit_view_tells_the_header_which_branches_are_remote_and_checked_out(qtbot):
    queries = MagicMock()
    queries.get_commit_detail.execute.return_value = COMMIT
    queries.get_branches.execute.return_value = [
        Branch(name="feature/login", is_remote=False, is_head=True, target_oid=OID),
        Branch(name="team/fix", is_remote=False, is_head=False, target_oid=OID),
        Branch(name="origin/main", is_remote=True, is_head=False, target_oid=OID),
    ]
    queries.get_commit_files.execute.return_value = [
        FileStatus(path="x.txt", status="staged", delta="modified")
    ]
    queries.list_submodules.execute.return_value = []
    widget = DiffWidget(queries, MagicMock())
    qtbot.addWidget(widget)
    widget.resize(1200, 800)
    widget.show()
    with patch("threading.Thread"):
        widget.load_commit(OID)

    colours = _painted_badge_colours(widget._detail)

    assert colours == {
        "feature/login": _role(ColorRole.BRANCH_HEAD_BG),
        "team/fix": _role(ColorRole.REF_BADGE_BRANCH_BG),
        "origin/main": _role(ColorRole.REF_BADGE_REMOTE_BG),
    }
