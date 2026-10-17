"""How the sidebar applies the results of its background loads.

Each load runs on a worker thread. These tests hold the workers and run them
in a chosen order, so the order results arrive in is part of the test rather
than a race.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt

from git_gui.domain.entities import Branch
from git_gui.presentation.widgets import sidebar as sidebar_module
from git_gui.presentation.widgets.sidebar import SidebarWidget


@pytest.fixture
def held_workers(monkeypatch) -> list:
    """Worker targets the sidebar started, in start order, not yet run."""
    held: list = []

    class _HeldThread:
        def __init__(self, target, daemon=False) -> None:
            self._target = target

        def start(self) -> None:
            held.append(self._target)

    monkeypatch.setattr(sidebar_module, "threading", SimpleNamespace(Thread=_HeldThread))
    return held


@pytest.fixture
def sidebar(qtbot):
    sb = SidebarWidget(queries=MagicMock(), commands=MagicMock())
    qtbot.addWidget(sb)
    return sb


def _bus(branch_name: str) -> MagicMock:
    queries = MagicMock()
    queries.get_branches.execute.return_value = [
        Branch(branch_name, is_remote=False, is_head=True, target_oid=f"{branch_name}-oid")
    ]
    queries.get_stashes.execute.return_value = []
    queries.get_tags.execute.return_value = []
    queries.list_local_branches_with_upstream.execute.return_value = []
    return queries


def _local_branch_names(sb: SidebarWidget) -> list[str]:
    header = sb._model.item(0)
    if header is None:
        return []
    return [header.child(r).data(Qt.UserRole) for r in range(header.rowCount())]


def test_a_slower_load_of_the_previous_repo_does_not_replace_the_current_one(sidebar, held_workers):
    sidebar.set_buses(_bus("repoA-main"), MagicMock())
    sidebar.set_buses(_bus("repoB-main"), MagicMock())
    load_a, load_b = held_workers

    load_b()
    load_a()

    assert _local_branch_names(sidebar) == ["repoB-main"]


def test_an_older_reload_finishing_last_does_not_bring_back_a_deleted_branch(sidebar, held_workers):
    queries = _bus("main")
    sidebar.set_buses(queries, MagicMock())
    sidebar.reload()
    older, newer = held_workers

    newer()
    # The older load read the refs before the branch was deleted.
    queries.get_branches.execute.return_value.append(
        Branch("deleted", is_remote=False, is_head=False, target_oid="d")
    )
    older()

    assert _local_branch_names(sidebar) == ["main"]


# ── A load that raises ──────────────────────────────────────────────────────
def _unreadable_bus() -> MagicMock:
    """A repo with a tag that cannot be peeled to a commit (it points at a tree)."""
    queries = _bus("unused")
    queries.get_tags.execute.side_effect = RuntimeError("can not be peeled into a commit")
    return queries


def test_a_failed_load_does_not_leave_the_previous_repos_rows(sidebar, held_workers):
    sidebar.set_buses(_bus("repoA-main"), MagicMock())
    held_workers.pop()()
    sidebar.set_buses(_unreadable_bus(), MagicMock())

    held_workers.pop()()

    assert _local_branch_names(sidebar) == []


def test_a_failed_load_says_why(sidebar, held_workers, qtbot):
    sidebar.set_buses(_unreadable_bus(), MagicMock())

    with qtbot.waitSignal(sidebar.load_failed, timeout=1000) as failure:
        held_workers.pop()()

    assert failure.args == ["can not be peeled into a commit"]


def test_an_older_load_failing_late_leaves_the_current_rows(sidebar, held_workers, qtbot):
    sidebar.set_buses(_unreadable_bus(), MagicMock())
    sidebar.set_buses(_bus("repoB-main"), MagicMock())
    failing, current = held_workers

    current()
    with qtbot.assertNotEmitted(sidebar.load_failed):
        failing()

    assert _local_branch_names(sidebar) == ["repoB-main"]


def test_a_load_still_running_when_the_repo_closes_is_dropped(sidebar, held_workers, qtbot):
    sidebar.set_buses(_unreadable_bus(), MagicMock())
    sidebar.set_buses(None, None)

    with qtbot.assertNotEmitted(sidebar.load_failed):
        held_workers.pop()()
