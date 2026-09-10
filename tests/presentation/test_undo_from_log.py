"""Tests for the Undo link the log offers after a destructive operation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QDialog

from git_gui.domain.entities import ResetMode
from git_gui.presentation.main_window.reflog_flow import ReflogFlowMixin
from git_gui.presentation.widgets.log_panel import ACTION_SCHEME, LogPanel

MODULE = "git_gui.presentation.main_window.reflog_flow"
GOOD = "a" * 40


class _Host(ReflogFlowMixin):
    def __init__(self) -> None:
        self._queries = MagicMock()
        self._commands = MagicMock()
        self._diff = MagicMock()
        self._log_panel = MagicMock()
        self._left_stack = MagicMock()
        self._right_stack = MagicMock()
        self._splitter = MagicMock()
        self._graph = MagicMock()
        self._graph_sizes = [220, 230, 950]
        self._blame_sizes = [220, 900, 480]
        self._selected_oid = None
        self._reflog_pane = None
        self._undoable: dict[str, str] = {}
        self.reloaded = 0

    def _reload(self) -> None:
        self.reloaded += 1

    def _close_blame_pane(self) -> None:
        pass


@pytest.fixture
def host():
    h = _Host()
    h._queries.get_head_oid.execute.return_value = GOOD
    h._queries.get_commit_detail.execute.return_value = MagicMock(message="the good state\n")
    h._queries.get_repo_state.execute.return_value = MagicMock(head_branch="main")
    h._queries.get_working_tree.execute.return_value = []
    return h


class _FakeResetDialog:
    Accepted = QDialog.Accepted
    result = QDialog.Accepted
    mode = ResetMode.HARD

    def __init__(self, **kwargs) -> None:
        pass

    def exec(self):
        return _FakeResetDialog.result

    def result_mode(self):
        return _FakeResetDialog.mode


def _dialog(*, accept: bool = True):
    _FakeResetDialog.result = QDialog.Accepted if accept else QDialog.Rejected
    return patch(f"{MODULE}.ResetDialog", _FakeResetDialog)


# ── The log panel's two kinds of link ────────────────────────────────────────


def test_an_action_link_reaches_the_app(qtbot):
    panel = LogPanel()
    qtbot.addWidget(panel)
    got: list[str] = []
    panel.action_triggered.connect(got.append)

    panel._body.anchorClicked.emit(QUrl(f"{ACTION_SCHEME}:/{GOOD}"))

    assert got == [GOOD]


def test_a_real_url_still_goes_to_the_browser(qtbot):
    """The update check posts a release link; it must not be swallowed."""
    panel = LogPanel()
    qtbot.addWidget(panel)
    reached_app: list[str] = []
    panel.action_triggered.connect(reached_app.append)
    opened: list[str] = []

    with patch(
        "git_gui.presentation.widgets.log_panel.QDesktopServices.openUrl",
        lambda url: opened.append(url.toString()),
    ):
        panel._body.anchorClicked.emit(QUrl("https://example.com/release"))

    assert opened == ["https://example.com/release"]
    assert reached_app == []


def test_log_action_renders_both_the_message_and_the_link(qtbot):
    panel = LogPanel()
    qtbot.addWidget(panel)

    panel.log_action("Reset main --hard to abc1234", "Undo", GOOD)

    text = panel._body.toPlainText()
    assert "Reset main --hard to abc1234" in text
    assert "Undo" in text
    assert ACTION_SCHEME in panel._body.toHtml()


# ── Capturing what to undo ───────────────────────────────────────────────────


def test_an_operation_offers_an_undo_back_to_where_head_was(host, qtbot):
    host._log_undoable("Rebase onto main", GOOD)

    host._log_panel.log_action.assert_called_once_with("Rebase onto main", "Undo", GOOD)
    assert host._undoable[GOOD] == "Rebase onto main"


def test_without_a_prior_head_the_line_is_logged_plainly(host, qtbot):
    """An unborn branch has nowhere to go back to; do not offer a dead link."""
    host._log_undoable("Cherry-pick: abc1234", None)

    host._log_panel.log.assert_called_once_with("Cherry-pick: abc1234")
    host._log_panel.log_action.assert_not_called()
    assert host._undoable == {}


def test_head_is_captured_before_the_operation_not_read_back_after(host, qtbot):
    """Reading HEAD@{1} at click time would undo whatever happened most
    recently, which need not be the operation the line reports."""
    assert host.head_before_operation() == GOOD

    host._queries.get_head_oid.execute.return_value = "later-state"
    host._log_undoable("Reset main --hard to xyz", GOOD)

    assert host._undoable[GOOD] == "Reset main --hard to xyz"


def test_a_failure_reading_head_does_not_break_the_operation(host, qtbot):
    host._queries.get_head_oid.execute.side_effect = RuntimeError("locked")
    assert host.head_before_operation() is None


# ── Clicking it ──────────────────────────────────────────────────────────────


def test_clicking_undo_resets_to_the_captured_state(host, qtbot):
    host._log_undoable("Reset main --hard to xyz", GOOD)

    with _dialog():
        host._on_log_action(GOOD)

    host._commands.reset_branch.execute.assert_called_once_with(GOOD, ResetMode.HARD)


def test_undo_goes_through_the_same_warning_as_any_reset(host, qtbot):
    """An undo is a reset, and as destructive as whatever it undoes."""
    host._log_undoable("Rebase onto main", GOOD)

    with _dialog(accept=False):
        host._on_log_action(GOOD)

    host._commands.reset_branch.execute.assert_not_called()


def test_an_unknown_action_id_does_nothing(host, qtbot):
    with _dialog():
        host._on_log_action("never-recorded")

    host._commands.reset_branch.execute.assert_not_called()
    assert host.reloaded == 0
