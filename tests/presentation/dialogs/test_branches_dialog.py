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
    with patch(
        "git_gui.presentation.dialogs.branches_dialog._RenameDialog"
    ) as RD:
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
    with patch(
        "git_gui.presentation.dialogs.branches_dialog._UpstreamDialog"
    ) as UD:
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
    with patch(
        "git_gui.presentation.dialogs.branches_dialog._UpstreamDialog"
    ) as UD:
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
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes), \
         patch.object(QMessageBox, "warning") as warn:
        d._on_delete()
    warn.assert_called_once()
    assert "boom" in warn.call_args[0][2]
