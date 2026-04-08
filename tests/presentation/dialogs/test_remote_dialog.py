from unittest.mock import MagicMock, patch
import pytest
from PySide6.QtWidgets import QMessageBox

from git_gui.domain.entities import Remote
from git_gui.presentation.dialogs.remote_dialog import RemoteDialog


@pytest.fixture
def buses():
    queries = MagicMock()
    commands = MagicMock()
    queries.list_remotes.execute.return_value = [
        Remote("origin", "git@x:a.git", "git@x:a.git"),
    ]
    return queries, commands


def test_dialog_populates_table_from_query(qtbot, buses):
    queries, commands = buses
    d = RemoteDialog(queries, commands)
    qtbot.addWidget(d)
    assert d._table.rowCount() == 1
    assert d._table.item(0, 0).text() == "origin"
    assert d._table.item(0, 1).text() == "git@x:a.git"


def test_remove_calls_command_and_refreshes(qtbot, buses):
    queries, commands = buses
    d = RemoteDialog(queries, commands)
    qtbot.addWidget(d)
    d._table.selectRow(0)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        d._on_remove()
    commands.remove_remote.execute.assert_called_once_with("origin")
    assert queries.list_remotes.execute.call_count >= 2


def test_error_shows_messagebox(qtbot, buses):
    queries, commands = buses
    commands.remove_remote.execute.side_effect = RuntimeError("boom")
    d = RemoteDialog(queries, commands)
    qtbot.addWidget(d)
    d._table.selectRow(0)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes), \
         patch.object(QMessageBox, "warning") as warn:
        d._on_remove()
    warn.assert_called_once()
    assert "boom" in warn.call_args[0][2]
