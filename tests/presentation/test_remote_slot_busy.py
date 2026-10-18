"""Operations that run in the remote-op slot say so when it is busy.

The slot runs one op at a time and drops a request made while one runs.
Interactive rebase and remote-branch delete both ask the user first, so
they check the slot before asking rather than lose what was confirmed.
"""

from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QMessageBox

from git_gui.presentation.main_window import MainWindow

_REBASE_DLG = "git_gui.presentation.main_window.merge_rebase_flows.InteractiveRebaseDialog"


def _busy_window(qtbot):
    repo_store = MagicMock()
    repo_store.get_open_repos.return_value = []
    repo_store.get_recent_repos.return_value = []
    repo_store.get_active.return_value = None
    win = MainWindow(
        queries=None,
        commands=None,
        repo_store=repo_store,
        session_factory=lambda _p: (MagicMock(), MagicMock()),
    )
    qtbot.addWidget(win)
    win._queries = MagicMock()
    win._commands = MagicMock()
    win._log_panel = MagicMock()
    win._remote_running = True
    return win


def test_interactive_rebase_is_not_offered_while_a_remote_op_runs(qtbot):
    win = _busy_window(qtbot)
    with patch(_REBASE_DLG) as dialog_cls:
        win._on_interactive_rebase_commit("a" * 40)
    dialog_cls.assert_not_called()
    win._commands.interactive_rebase.execute.assert_not_called()
    assert "skipped" in win._log_panel.log_error.call_args.args[0]


def test_remote_branch_delete_is_not_confirmed_while_a_remote_op_runs(qtbot):
    win = _busy_window(qtbot)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes) as question:
        win._on_delete_remote_branch("origin", "topic")
    question.assert_not_called()
    win._commands.delete_remote_branch.execute.assert_not_called()
    assert "skipped" in win._log_panel.log_error.call_args.args[0]


def test_a_free_slot_lets_the_op_through_without_a_message(qtbot):
    win = _busy_window(qtbot)
    win._remote_running = False
    assert win._remote_slot_busy("Fetch origin") is False
    win._log_panel.log_error.assert_not_called()


def test_a_skipped_interactive_rebase_names_the_op_that_holds_the_slot(qtbot):
    win = _busy_window(qtbot)
    win._remote_op_name = "Fetch origin"
    with patch(_REBASE_DLG):
        win._on_interactive_rebase_commit("a" * 40)
    assert "Fetch origin" in win._log_panel.log_error.call_args.args[0]


def test_a_skipped_remote_branch_delete_names_the_op_that_holds_the_slot(qtbot):
    win = _busy_window(qtbot)
    win._remote_op_name = "Fetch origin"
    win._on_delete_remote_branch("origin", "topic")
    assert "Fetch origin" in win._log_panel.log_error.call_args.args[0]
