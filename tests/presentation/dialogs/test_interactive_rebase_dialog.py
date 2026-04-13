"""Tests for InteractiveRebaseDialog."""
from __future__ import annotations
from datetime import datetime

import pytest
from PySide6.QtWidgets import QComboBox, QDialogButtonBox

from git_gui.domain.entities import Commit
from git_gui.presentation.dialogs.interactive_rebase_dialog import (
    InteractiveRebaseDialog,
)


def _commits():
    return [
        Commit(oid="aaa111", message="first commit", author="a", timestamp=datetime.now(), parents=[]),
        Commit(oid="bbb222", message="second commit", author="a", timestamp=datetime.now(), parents=["aaa111"]),
        Commit(oid="ccc333", message="third commit", author="a", timestamp=datetime.now(), parents=["bbb222"]),
    ]


def test_default_action_is_pick(qtbot):
    dlg = InteractiveRebaseDialog(_commits(), "main")
    qtbot.addWidget(dlg)
    for row in range(dlg._table.rowCount()):
        combo = dlg._table.cellWidget(row, 0)
        assert combo.currentText() == "pick"


def test_rows_match_commit_count(qtbot):
    commits = _commits()
    dlg = InteractiveRebaseDialog(commits, "main")
    qtbot.addWidget(dlg)
    assert dlg._table.rowCount() == 3


def test_commit_order_is_oldest_first(qtbot):
    commits = _commits()
    dlg = InteractiveRebaseDialog(commits, "main")
    qtbot.addWidget(dlg)
    # First row should be the oldest commit
    assert dlg._table.item(0, 1).text() == "aaa111"[:7]


def test_squash_on_first_row_disables_execute(qtbot):
    dlg = InteractiveRebaseDialog(_commits(), "main")
    qtbot.addWidget(dlg)
    combo = dlg._table.cellWidget(0, 0)
    combo.setCurrentText("squash")
    execute_btn = dlg._buttons.button(QDialogButtonBox.Ok)
    assert execute_btn.isEnabled() is False


def test_fixup_on_first_row_disables_execute(qtbot):
    dlg = InteractiveRebaseDialog(_commits(), "main")
    qtbot.addWidget(dlg)
    combo = dlg._table.cellWidget(0, 0)
    combo.setCurrentText("fixup")
    execute_btn = dlg._buttons.button(QDialogButtonBox.Ok)
    assert execute_btn.isEnabled() is False


def test_pick_on_first_row_enables_execute(qtbot):
    dlg = InteractiveRebaseDialog(_commits(), "main")
    qtbot.addWidget(dlg)
    # Change to squash then back to pick
    combo = dlg._table.cellWidget(0, 0)
    combo.setCurrentText("squash")
    combo.setCurrentText("pick")
    execute_btn = dlg._buttons.button(QDialogButtonBox.Ok)
    assert execute_btn.isEnabled() is True


def test_result_entries_returns_actions_and_oids(qtbot):
    commits = _commits()
    dlg = InteractiveRebaseDialog(commits, "main")
    qtbot.addWidget(dlg)
    # Change second to squash, third to drop
    dlg._table.cellWidget(1, 0).setCurrentText("squash")
    dlg._table.cellWidget(2, 0).setCurrentText("drop")
    result = dlg.result_entries()
    assert result == [
        ("pick", "aaa111"),
        ("squash", "bbb222"),
        ("drop", "ccc333"),
    ]
