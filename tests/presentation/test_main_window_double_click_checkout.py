"""Double-click-a-commit-to-switch-branch flow (BranchFlowsMixin).

Covers _on_commit_double_clicked and its helpers: single vs multiple branch
resolution, the picker dialog, local-vs-remote preference, and the
offer-to-reset-to-remote-when-diverged prompt.
"""

from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QDialog, QMessageBox

from git_gui.domain.entities import Branch, LocalBranchInfo
from git_gui.presentation.main_window import MainWindow

_DLG = "git_gui.presentation.main_window.branch_flows.BranchSelectDialog"


def _make_window(qtbot):
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
    win._graph = MagicMock()
    win._queries.get_head_oid.execute.return_value = "abc"
    win._queries.list_local_branches_with_upstream.execute.return_value = []
    return win


def test_single_local_branch_checks_out_directly(qtbot):
    win = _make_window(qtbot)
    win._queries.get_branches.execute.return_value = [
        Branch("feature", False, False, "abc"),
    ]
    with patch(_DLG) as Dlg, patch.object(win, "_reload"):
        win._on_commit_double_clicked("abc")
        Dlg.assert_not_called()  # single branch → no dialog
    win._commands.checkout.execute.assert_called_once_with("feature")


def test_no_branch_on_commit_is_noop(qtbot):
    win = _make_window(qtbot)
    win._queries.get_branches.execute.return_value = [
        Branch("feature", False, False, "otheroid"),  # not on this commit
    ]
    with patch(_DLG) as Dlg, patch.object(win, "_reload"):
        win._on_commit_double_clicked("abc")
        Dlg.assert_not_called()
    win._commands.checkout.execute.assert_not_called()


def test_multiple_local_branches_show_picker(qtbot):
    win = _make_window(qtbot)
    win._queries.get_branches.execute.return_value = [
        Branch("feature-a", False, False, "abc"),
        Branch("feature-b", False, False, "abc"),
    ]
    with patch(_DLG) as Dlg, patch.object(win, "_reload"):
        Dlg.return_value.exec.return_value = QDialog.Accepted
        Dlg.return_value.selected.return_value = "feature-b"
        win._on_commit_double_clicked("abc")
        # Dialog offered exactly the two candidate names.
        assert Dlg.call_args.args[0] == ["feature-a", "feature-b"]
    win._commands.checkout.execute.assert_called_once_with("feature-b")


def test_picker_cancelled_does_nothing(qtbot):
    win = _make_window(qtbot)
    win._queries.get_branches.execute.return_value = [
        Branch("feature-a", False, False, "abc"),
        Branch("feature-b", False, False, "abc"),
    ]
    with patch(_DLG) as Dlg, patch.object(win, "_reload"):
        Dlg.return_value.exec.return_value = QDialog.Rejected
        win._on_commit_double_clicked("abc")
    win._commands.checkout.execute.assert_not_called()


def test_prefers_local_over_remote_no_dialog(qtbot):
    """A commit carrying both a local branch and its remote counterpart
    resolves to the single local branch — no picker."""
    win = _make_window(qtbot)
    win._queries.get_branches.execute.return_value = [
        Branch("main", False, False, "abc"),
        Branch("origin/main", True, False, "abc"),
    ]
    with patch(_DLG) as Dlg, patch.object(win, "_reload"):
        win._on_commit_double_clicked("abc")
        Dlg.assert_not_called()
    win._commands.checkout.execute.assert_called_once_with("main")


def test_remote_only_branch_delegates_to_remote_checkout(qtbot):
    win = _make_window(qtbot)
    win._queries.get_branches.execute.return_value = [
        Branch("origin/dev", True, False, "abc"),
    ]
    with patch(_DLG), patch.object(win, "_reload"):
        win._on_commit_double_clicked("abc")
    # No local counterpart → _on_checkout_branch creates the tracking branch.
    win._commands.checkout_remote_branch.execute.assert_called_once_with("origin/dev")


def test_diverged_local_offers_reset_to_remote_yes(qtbot):
    win = _make_window(qtbot)
    win._queries.get_branches.execute.return_value = [
        Branch("main", False, False, "localoid"),
        Branch("origin/main", True, False, "remoteoid"),  # differs → diverged
    ]
    win._queries.list_local_branches_with_upstream.execute.return_value = [
        LocalBranchInfo("main", "origin/main", "localoid12", "msg"),
    ]
    with (
        patch(_DLG),
        patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
        patch.object(win, "_reload"),
    ):
        win._on_commit_double_clicked("localoid")
    win._commands.checkout.execute.assert_called_once_with("main")
    win._commands.reset_branch_to_ref.execute.assert_called_once_with("main", "origin/main")


def test_diverged_local_offers_reset_to_remote_no(qtbot):
    win = _make_window(qtbot)
    win._queries.get_branches.execute.return_value = [
        Branch("main", False, False, "localoid"),
        Branch("origin/main", True, False, "remoteoid"),
    ]
    win._queries.list_local_branches_with_upstream.execute.return_value = [
        LocalBranchInfo("main", "origin/main", "localoid12", "msg"),
    ]
    with (
        patch(_DLG),
        patch.object(QMessageBox, "question", return_value=QMessageBox.No),
        patch.object(win, "_reload"),
    ):
        win._on_commit_double_clicked("localoid")
    win._commands.checkout.execute.assert_called_once_with("main")
    win._commands.reset_branch_to_ref.execute.assert_not_called()


def test_in_sync_local_does_not_offer_reset(qtbot):
    """Local and upstream at the same oid → no reset prompt at all."""
    win = _make_window(qtbot)
    win._queries.get_branches.execute.return_value = [
        Branch("main", False, False, "sameoid"),
        Branch("origin/main", True, False, "sameoid"),
    ]
    win._queries.list_local_branches_with_upstream.execute.return_value = [
        LocalBranchInfo("main", "origin/main", "sameoid1234", "msg"),
    ]
    with (
        patch(_DLG),
        patch.object(QMessageBox, "question") as question,
        patch.object(win, "_reload"),
    ):
        win._on_commit_double_clicked("sameoid")
        question.assert_not_called()
    win._commands.checkout.execute.assert_called_once_with("main")
    win._commands.reset_branch_to_ref.execute.assert_not_called()


def test_local_without_upstream_does_not_offer_reset(qtbot):
    win = _make_window(qtbot)
    win._queries.get_branches.execute.return_value = [
        Branch("main", False, False, "abc"),
    ]
    win._queries.list_local_branches_with_upstream.execute.return_value = [
        LocalBranchInfo("main", None, "abcdef1234", "msg"),  # no upstream
    ]
    with (
        patch(_DLG),
        patch.object(QMessageBox, "question") as question,
        patch.object(win, "_reload"),
    ):
        win._on_commit_double_clicked("abc")
        question.assert_not_called()
    win._commands.reset_branch_to_ref.execute.assert_not_called()
