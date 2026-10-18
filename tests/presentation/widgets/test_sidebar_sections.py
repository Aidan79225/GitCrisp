"""The sections the sidebar builds from a finished load."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from git_gui.domain.entities import Branch, Stash
from git_gui.presentation.widgets.sidebar import _IS_HEAD_ROLE, SidebarWidget


@pytest.fixture
def sidebar(qtbot):
    sb = SidebarWidget(queries=MagicMock(), commands=MagicMock())
    qtbot.addWidget(sb)
    return sb


def _section(sb, title: str) -> list[str]:
    model = sb._model
    header = next(model.item(r) for r in range(model.rowCount()) if model.item(r).text() == title)
    return [header.child(r).text() for r in range(header.rowCount())]


def test_the_sections_come_in_a_fixed_order(sidebar):
    sidebar._on_load_done([], [], [], set(), {})

    titles = [sidebar._model.item(r).text() for r in range(sidebar._model.rowCount())]

    assert titles == ["LOCAL BRANCHES", "REMOTE BRANCHES", "STASHES", "TAGS"]


def test_stashes_are_listed_newest_first_with_undated_ones_last(sidebar):
    stashes = [
        Stash(0, "undated", "o0"),
        Stash(1, "older", "o1", datetime(2026, 1, 1, tzinfo=UTC)),
        Stash(2, "newer", "o2", datetime(2026, 6, 1, tzinfo=UTC)),
    ]

    sidebar._on_load_done([], stashes, [], set(), {})

    assert _section(sidebar, "STASHES") == ["newer", "older", "undated"]


def test_only_the_head_branch_is_flagged_for_the_highlight(sidebar):
    branches = [
        Branch("main", is_remote=False, is_head=True, target_oid="a1"),
        Branch("topic", is_remote=False, is_head=False, target_oid="b2"),
    ]

    sidebar._on_load_done(branches, [], [], set(), {})

    header = sidebar._model.item(0)
    flagged = [
        header.child(r).text()
        for r in range(header.rowCount())
        if header.child(r).data(_IS_HEAD_ROLE)
    ]
    assert flagged == ["main"]
