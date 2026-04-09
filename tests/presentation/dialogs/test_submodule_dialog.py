from unittest.mock import MagicMock, patch
import pytest
from PySide6.QtWidgets import QMessageBox

from git_gui.domain.entities import Submodule
from git_gui.presentation.dialogs.submodule_dialog import SubmoduleDialog


@pytest.fixture
def buses():
    queries = MagicMock()
    commands = MagicMock()
    queries.list_submodules.execute.return_value = [
        Submodule("libs/foo", "git@x:foo.git", "abcdef1234"),
    ]
    return queries, commands


def test_dialog_populates_table(qtbot, buses):
    queries, commands = buses
    d = SubmoduleDialog(queries, commands, repo_workdir="/tmp/parent")
    qtbot.addWidget(d)
    assert d._table.rowCount() == 1
    assert d._table.item(0, 0).text() == "libs/foo"
    assert d._table.item(0, 1).text() == "git@x:foo.git"


def test_remove_calls_command(qtbot, buses):
    queries, commands = buses
    d = SubmoduleDialog(queries, commands, repo_workdir="/tmp/parent")
    qtbot.addWidget(d)
    d._table.selectRow(0)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        d._on_remove()
    commands.remove_submodule.execute.assert_called_once_with("libs/foo")


def test_open_emits_absolute_path(qtbot, buses):
    queries, commands = buses
    d = SubmoduleDialog(queries, commands, repo_workdir="/tmp/parent")
    qtbot.addWidget(d)
    d._table.selectRow(0)
    captured: list[str] = []
    d.submoduleOpenRequested.connect(captured.append)
    d._on_open()
    assert len(captured) == 1
    assert captured[0].replace("\\", "/").endswith("parent/libs/foo")


def test_error_shows_messagebox(qtbot, buses):
    queries, commands = buses
    commands.remove_submodule.execute.side_effect = RuntimeError("boom")
    d = SubmoduleDialog(queries, commands, repo_workdir="/tmp/parent")
    qtbot.addWidget(d)
    d._table.selectRow(0)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes), \
         patch.object(QMessageBox, "warning") as warn:
        d._on_remove()
    warn.assert_called_once()
    assert "boom" in warn.call_args[0][2]
