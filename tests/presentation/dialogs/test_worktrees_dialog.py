"""Signal-contract tests for WorktreesDialog."""

from __future__ import annotations

from git_gui.domain.entities import Worktree
from git_gui.presentation.dialogs.worktrees_dialog import WorktreesDialog


def _wt(branch="feat", path="/tmp/wt", locked=False, reason=None, main=False):
    return Worktree(
        path=path,
        branch=branch,
        head_sha="abc",
        is_locked=locked,
        lock_reason=reason,
        is_bare=False,
        is_main=main,
    )


def _open(qtbot, worktrees):
    dlg = WorktreesDialog(worktrees=worktrees)
    qtbot.addWidget(dlg)
    return dlg


def test_rows_render_branch_and_path(qtbot):
    dlg = _open(qtbot, [_wt("main", "/tmp/main", main=True), _wt("feat", "/tmp/wt-feat")])
    assert dlg.row_count() == 2
    assert dlg.row_branch(0) == "main"
    assert dlg.row_path(1) == "/tmp/wt-feat"


def test_locked_column_shows_reason(qtbot):
    dlg = _open(qtbot, [_wt("feat", locked=True, reason="busy")])
    assert "busy" in dlg.row_locked_text(0).lower() or dlg.row_locked_text(0) == "Locked"


def test_open_button_emits_open_requested(qtbot):
    dlg = _open(qtbot, [_wt("feat", "/tmp/wt-feat")])
    received: list[str] = []
    dlg.open_requested.connect(received.append)
    dlg.select_row(0)
    dlg.click_open()
    assert received == ["/tmp/wt-feat"]


def test_remove_button_emits_remove_requested(qtbot):
    dlg = _open(qtbot, [_wt("feat", "/tmp/wt-feat")])
    received: list[str] = []
    dlg.remove_requested.connect(received.append)
    dlg.select_row(0)
    dlg.click_remove()
    assert received == ["/tmp/wt-feat"]


def test_lock_button_emits_lock_requested_for_unlocked_row(qtbot):
    dlg = _open(qtbot, [_wt("feat", "/tmp/wt-feat", locked=False)])
    received: list = []
    dlg.lock_requested.connect(lambda p, r: received.append((p, r)))
    dlg.select_row(0)
    dlg.click_lock(reason_for_test="overnight")
    assert received == [("/tmp/wt-feat", "overnight")]


def test_unlock_button_emits_unlock_requested_for_locked_row(qtbot):
    dlg = _open(qtbot, [_wt("feat", "/tmp/wt-feat", locked=True)])
    received: list[str] = []
    dlg.unlock_requested.connect(received.append)
    dlg.select_row(0)
    dlg.click_unlock()
    assert received == ["/tmp/wt-feat"]


def test_add_button_emits_add_requested(qtbot):
    dlg = _open(qtbot, [])
    received: list = []
    dlg.add_requested.connect(lambda: received.append(True))
    dlg.click_add()
    assert received == [True]
