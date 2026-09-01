"""Tests for opening the reflog and restoring a ref through it."""

from __future__ import annotations

from typing import ClassVar
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QDialog

from git_gui.domain.entities import ResetMode
from git_gui.presentation.main_window.reflog_flow import ReflogFlowMixin

MODULE = "git_gui.presentation.main_window.reflog_flow"


class _Host(ReflogFlowMixin):
    """Bare composite standing in for MainWindow's attributes."""

    def __init__(self) -> None:
        self._queries = MagicMock()
        self._commands = MagicMock()
        self._diff = MagicMock()
        self._log_panel = MagicMock()
        self._left_stack = MagicMock()
        self._right_stack = MagicMock()
        self._splitter = MagicMock()
        self._graph_sizes = [220, 230, 950]
        self._blame_sizes = [220, 900, 480]
        self._selected_oid = None
        self._reflog_pane = None
        self._blame_pane = None
        self.reloaded = 0
        self.closed_blame = 0

    def _reload(self) -> None:
        self.reloaded += 1

    def _close_blame_pane(self) -> None:
        self.closed_blame += 1


@pytest.fixture
def host():
    h = _Host()
    h._queries.get_commit_detail.execute.return_value = MagicMock(message="the good state\n")
    h._queries.get_repo_state.execute.return_value = MagicMock(head_branch="main")
    h._queries.get_working_tree.execute.return_value = []
    return h


# ── Opening ──────────────────────────────────────────────────────────────────


def test_opening_puts_the_reflog_in_the_commit_list_column(host, qtbot):
    with patch(f"{MODULE}.ReflogPane") as factory:
        host.open_reflog()

    factory.assert_called_once_with(host._queries)
    host._left_stack.setCurrentWidget.assert_called_once_with(factory.return_value)
    host._splitter.setSizes.assert_called_once_with(host._blame_sizes)


def test_opening_the_reflog_closes_blame(host, qtbot):
    """One column, one pane."""
    with patch(f"{MODULE}.ReflogPane"):
        host.open_reflog()

    assert host.closed_blame == 1


def test_opening_twice_focuses_the_pane_rather_than_stacking(host, qtbot):
    with patch(f"{MODULE}.ReflogPane") as factory:
        host.open_reflog()
        host.open_reflog()

    assert factory.call_count == 1
    factory.return_value.setFocus.assert_called()


def test_nothing_opens_without_a_repo(host, qtbot):
    host._queries = None
    with patch(f"{MODULE}.ReflogPane") as factory:
        host.open_reflog()

    factory.assert_not_called()
    assert host._reflog_pane is None


def test_closing_gives_the_column_back(host, qtbot):
    with patch(f"{MODULE}.ReflogPane") as factory:
        host.open_reflog()
        pane = factory.return_value
        host._close_reflog_pane()

    assert host._reflog_pane is None
    host._left_stack.setCurrentIndex.assert_called_with(0)
    host._left_stack.removeWidget.assert_called_once_with(pane)
    host._splitter.setSizes.assert_called_with(host._graph_sizes)


def test_closing_twice_is_harmless(host, qtbot):
    host._close_reflog_pane()
    host._close_reflog_pane()
    assert host._reflog_pane is None


# ── Picking a row ────────────────────────────────────────────────────────────


def test_picking_a_row_shows_that_state_in_the_diff(host, qtbot):
    """The commit list cannot show these at all once nothing references them."""
    host._on_reflog_commit_selected("deadbeef")

    host._diff.load_commit.assert_called_once_with("deadbeef")
    host._right_stack.setCurrentIndex.assert_called_once_with(0)
    assert host._selected_oid == "deadbeef"


# ── Restoring ────────────────────────────────────────────────────────────────


class _FakeResetDialog:
    """Stand-in for ResetDialog.

    A MagicMock will not do: the flow compares exec()'s result against
    ResetDialog.Accepted, and on a mock class that attribute is another mock,
    so the comparison silently fails and nothing is reset.
    """

    Accepted = QDialog.Accepted
    Rejected = QDialog.Rejected
    result = QDialog.Accepted
    mode = ResetMode.HARD
    kwargs: ClassVar[dict] = {}

    def __init__(self, **kwargs) -> None:
        _FakeResetDialog.kwargs = kwargs

    def exec(self):
        return _FakeResetDialog.result

    def result_mode(self):
        return _FakeResetDialog.mode


def _dialog(*, accept: bool = True, mode: ResetMode = ResetMode.HARD):
    _FakeResetDialog.result = QDialog.Accepted if accept else QDialog.Rejected
    _FakeResetDialog.mode = mode
    _FakeResetDialog.kwargs = {}
    return patch(f"{MODULE}.ResetDialog", _FakeResetDialog)


def test_restoring_runs_the_reset_the_user_confirmed(host, qtbot):
    with _dialog(mode=ResetMode.MIXED):
        host._on_reflog_restore_requested("cafebabe", "@{0} reset: moving to HEAD~2")

    host._commands.reset_branch.execute.assert_called_once_with("cafebabe", ResetMode.MIXED)


def test_restore_warns_through_the_same_dialog_as_any_other_reset(host, qtbot):
    """Restoring is as destructive as the operation it undoes."""
    with _dialog():
        host._on_reflog_restore_requested("cafebabe", "@{0} reset: moving to HEAD~2")

    kwargs = _FakeResetDialog.kwargs
    assert kwargs["default_mode"] is ResetMode.HARD
    assert kwargs["branch_name"] == "main"
    assert kwargs["dirty_files"] == []


def test_declining_the_dialog_changes_nothing(host, qtbot):
    with _dialog(accept=False):
        host._on_reflog_restore_requested("cafebabe", "@{0} reset")

    host._commands.reset_branch.execute.assert_not_called()
    assert host.reloaded == 0


def test_the_log_line_names_what_was_undone(host, qtbot):
    with _dialog():
        host._on_reflog_restore_requested("cafebabe", "@{0} reset: moving to HEAD~2")

    logged = host._log_panel.log.call_args.args[0]
    assert "cafebab" in logged
    assert "reset: moving to HEAD~2" in logged, "the entry being undone belongs in the record"


def test_restoring_closes_the_pane_and_rereads(host, qtbot):
    """The reflog just grew an entry of its own, and the commit list has moved."""
    with patch(f"{MODULE}.ReflogPane"), _dialog():
        host.open_reflog()
        host._on_reflog_restore_requested("cafebabe", "@{0} reset")

    assert host._reflog_pane is None
    assert host.reloaded == 1


def test_a_failed_restore_is_surfaced_and_does_not_reread(host, qtbot):
    host._commands.reset_branch.execute.side_effect = RuntimeError("locked")
    with _dialog():
        host._on_reflog_restore_requested("cafebabe", "@{0} reset")

    assert "locked" in host._log_panel.log_error.call_args.args[0]
    assert host.reloaded == 0


# ── The menu item is live from startup ───────────────────────────────────────


def test_git_menu_items_are_wired_before_any_repo_switch(qtbot, repo_path):
    """A menu item that opens nothing is worse than no menu item.

    The Git menu used to be built at three call sites whose arguments had
    drifted: the one that runs at startup passed neither the worktrees nor the
    reflog callback, so both did nothing until the user switched repos.
    """
    from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
    from git_gui.infrastructure.repo_store import JsonRepoStore
    from git_gui.presentation.main_window import MainWindow
    from main import _open_session

    queries, commands = _open_session(str(repo_path))
    window = MainWindow(
        queries,
        commands,
        JsonRepoStore(),
        JsonRemoteTagCache(),
        str(repo_path),
        session_factory=_open_session,
    )
    qtbot.addWidget(window)

    opened: list[str] = []
    window._open_worktrees_dialog = lambda: opened.append("worktrees")
    window.open_reflog = lambda: opened.append("reflog")
    window._install_git_menu()  # rebind to the stubs

    menu = next(a.menu() for a in window.menuBar().actions() if a.text() == "&Git")
    for label in ("&Worktrees...", "Ref&log..."):
        next(a for a in menu.actions() if a.text() == label).trigger()

    assert opened == ["worktrees", "reflog"]
