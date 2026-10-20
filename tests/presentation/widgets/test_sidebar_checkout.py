"""The branch context menu's Checkout hands the branch to the window's checkout
flow, as double-click does, rather than checking it out itself.

The flow is where a branch held by another worktree is noticed before the
working tree is touched, and where the checkout is logged and followed by a
reload; a second route that skipped it lost all three.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from git_gui.presentation.widgets.sidebar import SidebarWidget


@pytest.fixture
def sidebar(qtbot):
    sb = SidebarWidget(queries=MagicMock(), commands=MagicMock())
    qtbot.addWidget(sb)
    return sb


def test_checkout_from_the_branch_menu_is_handed_to_the_checkout_flow(sidebar, qtbot):
    with qtbot.waitSignal(sidebar.checkout_branch_requested, timeout=1000) as blocker:
        sidebar.trigger_branch_action("checkout", "feat")

    assert blocker.args == ["feat"]


def test_the_sidebar_checks_out_nothing_itself(sidebar):
    sidebar.trigger_branch_action("checkout", "feat")

    sidebar._commands.checkout.execute.assert_not_called()
    sidebar._queries.find_worktree_for_branch.execute.assert_not_called()
