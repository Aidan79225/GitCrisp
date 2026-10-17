from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QMessageBox

from git_gui.domain.entities import Branch, LocalBranchInfo
from git_gui.presentation.dialogs.branches_dialog import BranchesDialog


@pytest.fixture
def buses():
    queries = MagicMock()
    commands = MagicMock()
    queries.list_local_branches_with_upstream.execute.return_value = [
        LocalBranchInfo("master", "origin/master", "abc1234567", "init"),
        LocalBranchInfo("wip", None, "def5678901", "WIP"),
    ]
    queries.get_branches.execute.return_value = [
        Branch("master", False, True, "abc"),
        Branch("wip", False, False, "def"),
        Branch("origin/master", True, False, "abc"),
    ]
    return queries, commands


def test_dialog_populates_table(qtbot, buses):
    queries, commands = buses
    d = BranchesDialog(queries, commands)
    qtbot.addWidget(d)
    assert d._table.rowCount() == 2
    assert d._table.item(0, 0).text() == "master"
    assert d._table.item(0, 1).text() == "origin/master"
    assert d._table.item(1, 1).text() == "(none)"


def test_delete_calls_command(qtbot, buses):
    queries, commands = buses
    d = BranchesDialog(queries, commands)
    qtbot.addWidget(d)
    d._table.selectRow(1)  # wip
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        d._on_delete()
    commands.delete_branch.execute.assert_called_once_with("wip")


def test_rename_calls_command(qtbot, buses):
    queries, commands = buses
    d = BranchesDialog(queries, commands)
    qtbot.addWidget(d)
    d._table.selectRow(1)
    with patch("git_gui.presentation.dialogs.branches_dialog._RenameDialog") as RD:
        instance = RD.return_value
        instance.exec.return_value = 1  # QDialog.Accepted
        instance.value.return_value = "wip2"
        d._on_rename()
    commands.rename_branch.execute.assert_called_once_with("wip", "wip2")


def test_set_upstream_calls_command(qtbot, buses):
    queries, commands = buses
    d = BranchesDialog(queries, commands)
    qtbot.addWidget(d)
    d._table.selectRow(1)
    with patch("git_gui.presentation.dialogs.branches_dialog._UpstreamDialog") as UD:
        instance = UD.return_value
        instance.exec.return_value = 1
        instance.value.return_value = "origin/master"
        d._on_set_upstream()
    commands.set_branch_upstream.execute.assert_called_once_with("wip", "origin/master")


def test_set_upstream_none_calls_unset(qtbot, buses):
    queries, commands = buses
    d = BranchesDialog(queries, commands)
    qtbot.addWidget(d)
    d._table.selectRow(0)
    with patch("git_gui.presentation.dialogs.branches_dialog._UpstreamDialog") as UD:
        instance = UD.return_value
        instance.exec.return_value = 1
        instance.value.return_value = None
        d._on_set_upstream()
    commands.unset_branch_upstream.execute.assert_called_once_with("master")


def test_error_shows_messagebox(qtbot, buses):
    queries, commands = buses
    commands.delete_branch.execute.side_effect = RuntimeError("boom")
    d = BranchesDialog(queries, commands)
    qtbot.addWidget(d)
    d._table.selectRow(1)
    with (
        patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
        patch.object(QMessageBox, "warning") as warn,
    ):
        d._on_delete()
    warn.assert_called_once()
    assert "boom" in warn.call_args[0][2]


def test_create_from_a_branch_name_start_point_creates_the_branch(qtbot, repo_impl):
    from PySide6.QtWidgets import QDialog

    from git_gui.presentation.bus import CommandBus, QueryBus

    queries = QueryBus.from_reader(repo_impl)
    commands = CommandBus.from_writer(repo_impl)
    d = BranchesDialog(queries, commands)
    qtbot.addWidget(d)
    d._table.selectRow(0)  # master: the Create dialog prefills its name as the start point
    with (
        patch("git_gui.presentation.dialogs.branches_dialog._CreateDialog") as CD,
        patch.object(QMessageBox, "warning") as warn,
    ):
        CD.return_value.exec.return_value = QDialog.Accepted
        CD.return_value.values.return_value = ("feat", "master")
        d._on_create()
    warn.assert_not_called()
    assert "feat" in {b.name for b in queries.get_branches.execute()}


def test_checkout_closes_the_dialog_and_hands_the_branch_to_the_window(qtbot, buses):
    """The window's checkout flow is what notices a branch held by another
    worktree before the working tree is touched, and logs and reloads."""
    from PySide6.QtWidgets import QDialog

    queries, commands = buses
    d = BranchesDialog(queries, commands)
    qtbot.addWidget(d)
    d._table.selectRow(1)  # wip

    with qtbot.waitSignal(d.checkout_requested, timeout=1000) as blocker:
        d._checkout_btn.click()

    assert blocker.args == ["wip"]
    assert d.result() == QDialog.Accepted
    commands.checkout.execute.assert_not_called()
