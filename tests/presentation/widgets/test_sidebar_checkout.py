"""The branch context menu's Checkout, once MainWindow has installed SmartCheckout.

SmartCheckout turns the "branch is in another worktree" error into a switch to
that worktree and re-raises everything else. The sidebar cannot report an
error itself, so whatever SmartCheckout re-raises has to reach the checkout
flow that does.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pygit2
import pytest

from git_gui.domain.entities import Worktree
from git_gui.presentation.services.smart_checkout import SmartCheckout
from git_gui.presentation.widgets.sidebar import SidebarWidget


class _Checkout:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.calls: list[str] = []

    def execute(self, branch: str) -> None:
        self.calls.append(branch)
        if self._error is not None:
            raise self._error


class _Finder:
    def __init__(self, worktree: Worktree | None) -> None:
        self._worktree = worktree

    def execute(self, branch: str) -> Worktree | None:
        return self._worktree


def _worktree(path: str, branch: str) -> Worktree:
    return Worktree(
        path=path,
        branch=branch,
        head_sha="x",
        is_locked=False,
        lock_reason=None,
        is_bare=False,
        is_main=False,
    )


@pytest.fixture
def sidebar(qtbot):
    sb = SidebarWidget(queries=MagicMock(), commands=MagicMock())
    qtbot.addWidget(sb)
    return sb


def test_a_failed_checkout_is_handed_to_the_flow_that_reports_it(sidebar, qtbot):
    conflict = pygit2.GitError("1 conflict prevents checkout")
    sidebar.set_smart_checkout(SmartCheckout(_Checkout(conflict), _Finder(None)))

    with qtbot.waitSignal(sidebar.checkout_branch_requested, timeout=1000) as blocker:
        sidebar.trigger_branch_action("checkout", "feat")

    assert blocker.args == ["feat"]


def test_a_successful_checkout_is_not_run_twice(sidebar, qtbot):
    checkout = _Checkout()
    sidebar.set_smart_checkout(SmartCheckout(checkout, _Finder(None)))

    with qtbot.assertNotEmitted(sidebar.checkout_branch_requested):
        sidebar.trigger_branch_action("checkout", "feat")

    assert checkout.calls == ["feat"]


def test_a_branch_owned_by_another_worktree_switches_there_instead(sidebar, qtbot):
    collision = pygit2.GitError("branch 'feat' already used by worktree at /wt/feat")
    smart = SmartCheckout(_Checkout(collision), _Finder(_worktree("/wt/feat", "feat")))
    sidebar.set_smart_checkout(smart)

    with (
        qtbot.waitSignal(smart.switch_to_worktree_requested, timeout=1000) as switched,
        qtbot.assertNotEmitted(sidebar.checkout_branch_requested),
    ):
        sidebar.trigger_branch_action("checkout", "feat")

    assert switched.args == ["/wt/feat"]
