"""Sidebar branch rows show a + badge when the branch owns a worktree,
and the branch context menu offers 'Checkout in New Worktree…'."""
from __future__ import annotations

from git_gui.presentation.widgets.sidebar import SidebarWidget


def _make(qtbot):
    """Construct a SidebarWidget with minimal stand-ins for QueryBus/CommandBus.
    The widget can render its tree without a real reload — we just need the
    branch-aware helper methods."""
    sb = SidebarWidget(queries=None, commands=None)
    qtbot.addWidget(sb)
    return sb


def test_set_worktree_branches_updates_state(qtbot):
    sb = _make(qtbot)
    sb.set_worktree_branches({"feat/a"})
    assert sb.has_worktree_badge("feat/a") is True
    assert sb.has_worktree_badge("master") is False


def test_branch_context_menu_contains_checkout_in_new_worktree(qtbot):
    sb = _make(qtbot)
    actions = sb.build_branch_context_actions("feat/a")
    labels = [a["label"] for a in actions]
    assert "Checkout in New Worktree…" in labels


def test_checkout_in_new_worktree_action_emits_signal(qtbot):
    sb = _make(qtbot)
    received: list[str] = []
    sb.checkout_in_new_worktree_requested.connect(received.append)
    sb.trigger_branch_action("checkout_in_new_worktree", "feat/a")
    assert received == ["feat/a"]
