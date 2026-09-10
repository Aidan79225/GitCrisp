"""Tests for the graph header's first-parent toggle button."""

from __future__ import annotations

from unittest.mock import MagicMock

from PySide6.QtWidgets import QApplication

from git_gui.presentation.widgets.graph import GraphWidget


def _app():
    return QApplication.instance() or QApplication([])


def _make_queries() -> MagicMock:
    """A queries bus that returns benign empty values for the reload worker."""
    q = MagicMock()
    q.get_commit_graph.execute.return_value = []
    q.get_branches.execute.return_value = []
    q.get_tags.execute.return_value = []
    q.is_dirty.execute.return_value = False
    q.get_head_oid.execute.return_value = ""
    q.get_repo_state.execute.return_value = MagicMock(head_branch=None)
    q.get_merge_head.execute.return_value = None
    return q


def test_set_repo_path_reads_persisted_setting_and_syncs_button(qtbot):
    _app()
    repo_store = MagicMock()
    repo_store.get_repo_setting.return_value = True
    queries = _make_queries()
    commands = MagicMock()

    w = GraphWidget(queries, commands, repo_store=repo_store)
    qtbot.addWidget(w)

    w.set_repo_path("/repo/a")

    repo_store.get_repo_setting.assert_called_with("/repo/a", "first_parent", False)
    assert w._first_parent is True
    assert w._first_parent_btn.isChecked() is True


def test_set_repo_path_none_resets_to_unchecked(qtbot):
    _app()
    repo_store = MagicMock()
    repo_store.get_repo_setting.return_value = True
    queries = _make_queries()
    commands = MagicMock()

    w = GraphWidget(queries, commands, repo_store=repo_store)
    qtbot.addWidget(w)
    w.set_repo_path("/repo/a")  # primes _first_parent True
    assert w._first_parent is True

    w.set_repo_path(None)
    assert w._first_parent is False
    assert w._first_parent_btn.isChecked() is False


def test_toggling_button_persists_and_reloads(qtbot):
    _app()
    repo_store = MagicMock()
    repo_store.get_repo_setting.return_value = False
    queries = _make_queries()
    commands = MagicMock()

    w = GraphWidget(queries, commands, repo_store=repo_store)
    qtbot.addWidget(w)
    w.set_repo_path("/repo/a")

    # User clicks the toggle.
    w._first_parent_btn.setChecked(True)

    repo_store.set_repo_setting.assert_called_with("/repo/a", "first_parent", True)
    repo_store.save.assert_called()
    assert w._first_parent is True
    qtbot.wait(50)  # let the background reload worker run
    # Reload is invoked via the worker thread on the queries bus; verify
    # at least one call to get_commit_graph.execute happened with first_parent=True.
    calls = queries.get_commit_graph.execute.call_args_list
    assert any(call.kwargs.get("first_parent") is True for call in calls), (
        f"expected at least one call with first_parent=True, got {calls}"
    )


def test_reload_passes_first_parent_flag(qtbot):
    """Without any toggle interaction, the reload worker still passes
    first_parent=<current state> (False by default)."""
    _app()
    repo_store = MagicMock()
    repo_store.get_repo_setting.return_value = False
    queries = _make_queries()
    commands = MagicMock()

    w = GraphWidget(queries, commands, repo_store=repo_store)
    qtbot.addWidget(w)
    w.set_repo_path("/repo/a")

    w.reload()
    qtbot.wait(50)  # let the background worker run

    calls = queries.get_commit_graph.execute.call_args_list
    assert calls, "expected get_commit_graph.execute to be called by reload"
    assert all(call.kwargs.get("first_parent") is False for call in calls)


def test_toggle_with_no_repo_path_does_not_persist(qtbot):
    """If no repo is active, toggling shouldn't crash trying to persist."""
    _app()
    repo_store = MagicMock()
    repo_store.get_repo_setting.return_value = False
    queries = _make_queries()
    commands = MagicMock()

    w = GraphWidget(queries, commands, repo_store=repo_store)
    qtbot.addWidget(w)
    # Skip set_repo_path entirely — _repo_path is None.
    w._first_parent_btn.setChecked(True)

    repo_store.set_repo_setting.assert_not_called()
    repo_store.save.assert_not_called()
