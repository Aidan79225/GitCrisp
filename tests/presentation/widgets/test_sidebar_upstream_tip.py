"""A local branch row carries its upstream's tip.

Clicking a branch pushes that tip into the graph walk alongside the branch's
own, so a branch that is behind still draws what its remote is holding ahead
of it. Rows only carry the tip when it says something the branch tip doesn't:
no upstream, or an upstream in sync, leaves the role unset.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from git_gui.domain.entities import Branch
from git_gui.presentation.widgets.sidebar import _UPSTREAM_OID_ROLE, SidebarWidget


@pytest.fixture
def sidebar(qtbot):
    sb = SidebarWidget(queries=MagicMock(), commands=MagicMock())
    qtbot.addWidget(sb)
    return sb


def _local_rows(sb) -> dict[str, str | None]:
    """{branch name: upstream oid on its row} for the LOCAL BRANCHES section."""
    header = sb._model.item(0)
    assert header.text() == "LOCAL BRANCHES"
    return {
        header.child(r).text(): header.child(r).data(_UPSTREAM_OID_ROLE)
        for r in range(header.rowCount())
    }


def _load(sb, branches, upstreams) -> None:
    sb._on_load_done(branches, [], [], set(), upstreams)


def test_a_branch_behind_its_remote_carries_the_remote_tip(sidebar):
    _load(
        sidebar,
        [
            Branch("feature", is_remote=False, is_head=True, target_oid="local1"),
            Branch("origin/feature", is_remote=True, is_head=False, target_oid="remote9"),
        ],
        {"feature": "origin/feature"},
    )
    assert _local_rows(sidebar) == {"feature": "remote9"}


def test_a_branch_in_sync_carries_nothing(sidebar):
    _load(
        sidebar,
        [
            Branch("feature", is_remote=False, is_head=True, target_oid="same"),
            Branch("origin/feature", is_remote=True, is_head=False, target_oid="same"),
        ],
        {"feature": "origin/feature"},
    )
    assert _local_rows(sidebar) == {"feature": None}


def test_a_branch_without_an_upstream_carries_nothing(sidebar):
    _load(
        sidebar,
        [Branch("local-only", is_remote=False, is_head=True, target_oid="local1")],
        {},
    )
    assert _local_rows(sidebar) == {"local-only": None}


def test_an_upstream_that_is_not_loaded_carries_nothing(sidebar):
    """The tracking ref is configured but no such remote branch came back —
    there is no tip to push, and no reason to fail over it."""
    _load(
        sidebar,
        [Branch("feature", is_remote=False, is_head=True, target_oid="local1")],
        {"feature": "origin/gone"},
    )
    assert _local_rows(sidebar) == {"feature": None}


def test_the_reload_worker_collects_upstreams_from_the_query_bus(sidebar, qtbot):
    from git_gui.domain.entities import LocalBranchInfo

    q = sidebar._queries
    q.get_branches.execute.return_value = [
        Branch("feature", is_remote=False, is_head=True, target_oid="local1"),
        Branch("origin/feature", is_remote=True, is_head=False, target_oid="remote9"),
    ]
    q.get_stashes.execute.return_value = []
    q.get_tags.execute.return_value = []
    q.list_local_branches_with_upstream.execute.return_value = [
        LocalBranchInfo("feature", "origin/feature", "local1", "msg"),
        LocalBranchInfo("no-upstream", None, "local2", "msg"),
    ]

    sidebar.reload()

    qtbot.waitUntil(lambda: sidebar._model.rowCount() > 0, timeout=2000)
    assert _local_rows(sidebar) == {"feature": "remote9"}
