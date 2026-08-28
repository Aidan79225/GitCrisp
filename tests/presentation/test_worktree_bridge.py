"""Tests for the 'Checkout in New Worktree…' bridge.

The connection used to be rebuilt on every repo switch and guarded by
`hasattr` checks that could never be false. It is bound once now, at
construction, because nothing about it depends on the open repo.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.presentation.main_window import MainWindow


@pytest.fixture
def window(qtbot, repo_path):
    from main import _open_session

    queries, commands = _open_session(str(repo_path))
    store = JsonRepoStore()
    w = MainWindow(
        queries,
        commands,
        store,
        JsonRemoteTagCache(),
        str(repo_path),
        session_factory=_open_session,
    )
    qtbot.addWidget(w)
    return w


def test_sidebar_request_opens_the_add_worktree_dialog(window):
    with patch.object(MainWindow, "_open_add_worktree_dialog") as opener:
        window._sidebar.checkout_in_new_worktree_requested.emit("feature/x")

    opener.assert_called_once_with(preselect_branch="feature/x", default_create=False)


def test_graph_request_opens_the_add_worktree_dialog(window):
    with patch.object(MainWindow, "_open_add_worktree_dialog") as opener:
        window._graph.checkout_in_new_worktree_requested.emit("feature/y")

    opener.assert_called_once_with(preselect_branch="feature/y", default_create=False)


def test_the_bridge_fires_exactly_once_per_request(window):
    """Rebinding per repo switch risked stacking duplicate connections."""
    calls: list[str] = []
    with patch.object(
        MainWindow,
        "_open_add_worktree_dialog",
        lambda self, **kw: calls.append(kw["preselect_branch"]),
    ):
        window._sidebar.checkout_in_new_worktree_requested.emit("once")

    assert calls == ["once"]


def test_a_repo_switch_does_not_stack_a_second_connection(window, qtbot, repo_path):
    """The binding is repo-independent, so reopening must not double it up."""
    from main import _open_session

    queries, commands = _open_session(str(repo_path))
    window._on_repo_ready(str(repo_path), queries, commands)
    qtbot.wait(50)

    calls: list[str] = []
    with patch.object(
        MainWindow,
        "_open_add_worktree_dialog",
        lambda self, **kw: calls.append(kw["preselect_branch"]),
    ):
        window._graph.checkout_in_new_worktree_requested.emit("after-switch")

    assert calls == ["after-switch"]


def test_the_bridge_is_bound_before_any_repo_is_opened(qtbot):
    """Binding belongs to construction, not to opening a repo.

    Nothing can emit before a repo is open, so this pins the invariant rather
    than covering an observed failure — but it is what makes the disconnect
    dance in _on_repo_ready unnecessary.
    """
    from main import _open_session

    w = MainWindow(
        None, None, JsonRepoStore(), JsonRemoteTagCache(), None, session_factory=_open_session
    )
    qtbot.addWidget(w)

    with patch.object(MainWindow, "_open_add_worktree_dialog") as opener:
        w._sidebar.checkout_in_new_worktree_requested.emit("no-repo-yet")

    opener.assert_called_once_with(preselect_branch="no-repo-yet", default_create=False)
