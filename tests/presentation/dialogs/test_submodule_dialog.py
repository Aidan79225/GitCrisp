import threading
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QDialog, QMessageBox

from git_gui.domain.entities import Submodule
from git_gui.presentation.dialogs.submodule_dialog import SubmoduleDialog, _SubmoduleAddDialog


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
    with (
        patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
        patch.object(QMessageBox, "warning") as warn,
    ):
        d._on_remove()
    warn.assert_called_once()
    assert "boom" in warn.call_args[0][2]


def _add_through_the_dialog(d, path="libs/big", url="https://example.com/big.git"):
    with (
        patch.object(_SubmoduleAddDialog, "exec", return_value=QDialog.Accepted),
        patch.object(_SubmoduleAddDialog, "values", return_value=(path, url)),
    ):
        d._on_add()


def test_adding_a_submodule_runs_off_the_gui_thread(qtbot, buses):
    queries, commands = buses
    adding_threads: list[threading.Thread] = []
    commands.add_submodule.execute.side_effect = lambda path, url: adding_threads.append(
        threading.current_thread()
    )
    d = SubmoduleDialog(queries, commands, repo_workdir="/tmp/parent")
    qtbot.addWidget(d)

    _add_through_the_dialog(d)

    qtbot.waitUntil(lambda: d._add_btn.isEnabled())
    assert adding_threads and adding_threads[0] is not threading.main_thread()


def test_the_dialog_stays_busy_until_the_add_finishes(qtbot, buses):
    queries, commands = buses
    gate = threading.Event()
    commands.add_submodule.execute.side_effect = lambda path, url: gate.wait(5)
    d = SubmoduleDialog(queries, commands, repo_workdir="/tmp/parent")
    qtbot.addWidget(d)
    d.show()

    _add_through_the_dialog(d)
    d.reject()

    assert d.isVisible()
    assert not d._close_btn.isEnabled()
    gate.set()
    qtbot.waitUntil(lambda: d._close_btn.isEnabled())
    assert queries.list_submodules.execute.call_count == 2


def test_a_failed_add_reports_the_error(qtbot, buses):
    queries, commands = buses
    commands.add_submodule.execute.side_effect = RuntimeError("could not read from remote")
    d = SubmoduleDialog(queries, commands, repo_workdir="/tmp/parent")
    qtbot.addWidget(d)

    with patch.object(QMessageBox, "warning") as warn:
        _add_through_the_dialog(d)
        qtbot.waitUntil(lambda: warn.called)

    assert "could not read from remote" in warn.call_args[0][2]
    assert d._add_btn.isEnabled()
