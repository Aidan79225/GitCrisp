"""Graph branch context menu: 'Checkout in New Worktree' wiring."""

from __future__ import annotations

from git_gui.domain.entities import Branch
from tests.presentation.widgets.graph_menu_helpers import ROW_OID, find_action, open_context_menu


def test_checkout_in_new_worktree_signal_exists():
    from git_gui.presentation.widgets.graph import GraphWidget

    assert hasattr(GraphWidget, "checkout_in_new_worktree_requested")


def test_branch_context_menu_offers_checkout_in_new_worktree(qtbot):
    gw, menu = open_context_menu(qtbot, [Branch("feat/x", False, False, ROW_OID)])
    received: list[str] = []
    gw.checkout_in_new_worktree_requested.connect(received.append)

    find_action(menu, "Checkout in New Worktree: feat/x").trigger()

    assert received == ["feat/x"]


def test_each_branch_on_the_commit_gets_its_own_worktree_entry(qtbot):
    gw, menu = open_context_menu(
        qtbot, [Branch("feat/x", False, False, ROW_OID), Branch("feat/y", False, False, ROW_OID)]
    )
    received: list[str] = []
    gw.checkout_in_new_worktree_requested.connect(received.append)

    find_action(menu, "feat/y", submenu="Checkout in New Worktree").trigger()

    assert received == ["feat/y"]
