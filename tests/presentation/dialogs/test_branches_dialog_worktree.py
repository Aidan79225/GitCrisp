"""Worktree integration in BranchesDialog: + badge column and new
'Checkout in New Worktree' button."""

from __future__ import annotations

from git_gui.domain.entities import LocalBranchInfo
from git_gui.presentation.dialogs.branches_dialog import BranchesDialog


class _Q:
    def __init__(self, infos):
        class _LBU:
            def __init__(self, infos):
                self._infos = infos

            def execute(self):
                return list(self._infos)

        class _GB:
            def execute(self):
                return []

        self.list_local_branches_with_upstream = _LBU(infos)
        self.get_branches = _GB()


class _C: ...


def _info(name, upstream=None):
    return LocalBranchInfo(
        name=name,
        upstream=upstream,
        last_commit_sha="abc1234",
        last_commit_message="msg",
    )


def test_branches_dialog_renders_worktree_column(qtbot):
    q = _Q([_info("master"), _info("feat/a")])
    dlg = BranchesDialog(q, _C())
    qtbot.addWidget(dlg)
    dlg.set_worktree_paths({"feat/a": "/tmp/wt-feat-a"})
    headers = [dlg._table.horizontalHeaderItem(i).text() for i in range(dlg._table.columnCount())]
    assert "Worktree" in headers
    for row in range(dlg._table.rowCount()):
        if dlg._table.item(row, 0).text().startswith("feat/a"):
            col = headers.index("Worktree")
            assert "/tmp/wt-feat-a" in dlg._table.item(row, col).text()
            break
    else:
        raise AssertionError("feat/a row not found")


def test_checkout_in_new_worktree_button_emits_signal(qtbot):
    q = _Q([_info("master")])
    dlg = BranchesDialog(q, _C())
    qtbot.addWidget(dlg)
    received: list[str] = []
    dlg.checkout_in_new_worktree_requested.connect(received.append)
    dlg._table.selectRow(0)
    dlg.click_checkout_in_new_worktree()
    assert received == ["master"]
