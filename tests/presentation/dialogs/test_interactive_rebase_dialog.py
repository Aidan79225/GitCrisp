"""Tests for InteractiveRebaseDialog."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QDialogButtonBox

from git_gui.domain.entities import Commit
from git_gui.presentation.dialogs.interactive_rebase_dialog import (
    InteractiveRebaseDialog,
)


def _commits():
    return [
        Commit(
            oid="aaa111", message="first commit", author="a", timestamp=datetime.now(), parents=[]
        ),
        Commit(
            oid="bbb222",
            message="second commit",
            author="a",
            timestamp=datetime.now(),
            parents=["aaa111"],
        ),
        Commit(
            oid="ccc333",
            message="third commit",
            author="a",
            timestamp=datetime.now(),
            parents=["bbb222"],
        ),
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


class _DropFromTheTable(QDropEvent):
    """A drop whose drag started in ``table``, as a real in-table drag reports it."""

    def __init__(self, table, pos, mime):
        super().__init__(QPointF(pos), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
        self._table = table

    def source(self):
        return self._table


def _drag_row(dlg, row, *, onto_row, upper_half):
    table = dlg._table
    table.selectRow(row)
    rect = table.visualRect(table.model().index(onto_row, 2))
    offset = rect.height() // 4
    pos = rect.center() + QPoint(0, -offset if upper_half else offset)
    mime = QMimeData()
    table.dropEvent(_DropFromTheTable(table, pos, mime))


def _shown_dialog(qtbot):
    dlg = InteractiveRebaseDialog(_commits(), "main")
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    dlg._table.cellWidget(2, 0).setCurrentText("drop")
    return dlg


def test_dragging_a_row_below_the_last_moves_the_whole_commit_to_the_end(qtbot):
    dlg = _shown_dialog(qtbot)
    _drag_row(dlg, 0, onto_row=2, upper_half=False)
    assert dlg.result_entries() == [
        ("pick", "bbb222"),
        ("drop", "ccc333"),
        ("pick", "aaa111"),
    ]


def test_dragging_a_row_onto_the_upper_half_of_another_lands_above_it(qtbot):
    dlg = _shown_dialog(qtbot)
    _drag_row(dlg, 2, onto_row=0, upper_half=True)
    assert dlg.result_entries() == [
        ("drop", "ccc333"),
        ("pick", "aaa111"),
        ("pick", "bbb222"),
    ]


def test_squash_after_only_dropped_rows_disables_execute(qtbot):
    dlg = InteractiveRebaseDialog(_commits(), "main")
    qtbot.addWidget(dlg)
    dlg._table.cellWidget(0, 0).setCurrentText("drop")
    dlg._table.cellWidget(1, 0).setCurrentText("squash")
    assert dlg._buttons.button(QDialogButtonBox.Ok).isEnabled() is False


def test_squash_after_a_kept_commit_and_a_drop_enables_execute(qtbot):
    dlg = InteractiveRebaseDialog(_commits(), "main")
    qtbot.addWidget(dlg)
    dlg._table.cellWidget(1, 0).setCurrentText("drop")
    dlg._table.cellWidget(2, 0).setCurrentText("fixup")
    assert dlg._buttons.button(QDialogButtonBox.Ok).isEnabled() is True


def test_commits_whose_short_oids_collide_each_keep_their_own_full_oid(qtbot):
    first, second = "abcdef1" + "0" * 33, "abcdef1" + "f" * 33
    commits = [
        Commit(oid=first, message="one", author="a", timestamp=datetime.now(), parents=[]),
        Commit(oid=second, message="two", author="a", timestamp=datetime.now(), parents=[first]),
    ]
    dlg = InteractiveRebaseDialog(commits, "main")
    qtbot.addWidget(dlg)
    assert dlg.result_entries() == [("pick", first), ("pick", second)]


def test_the_plan_names_each_action_as_a_rebase_action(qtbot):
    from git_gui.domain.entities import RebaseAction

    dlg = InteractiveRebaseDialog(_commits(), "main")
    qtbot.addWidget(dlg)
    dlg._table.cellWidget(1, 0).setCurrentText("fixup")
    actions = [action for action, _oid in dlg.result_entries()]
    assert actions == [RebaseAction.PICK, RebaseAction.FIXUP, RebaseAction.PICK]
    assert all(type(action) is RebaseAction for action in actions)
    assert [dlg._table.cellWidget(0, 0).itemText(i) for i in range(4)] == [
        "pick",
        "squash",
        "fixup",
        "drop",
    ]
