from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from git_gui.domain.entities import Branch, RemoteBranchDeleteResult
from git_gui.presentation.dialogs.remote_branches_dialog import RemoteBranchesDialog


def _make(qtbot, branches=None, defaults=None):
    queries = MagicMock()
    commands = MagicMock()
    queries.get_branches.execute.return_value = branches or [
        Branch("origin/feature-a", True, False, "a"),
        Branch("origin/feature-b", True, False, "b"),
        Branch("origin/main", True, False, "c"),
        Branch("origin/HEAD", True, False, "c"),
        Branch("local", False, True, "d"),
    ]
    queries.remote_default_branches.execute.return_value = defaults or {"origin": "origin/main"}
    dlg = RemoteBranchesDialog(queries, commands)
    qtbot.addWidget(dlg)
    return dlg, queries, commands


def _rows_by_name(dlg):
    out = {}
    for row in range(dlg._table.rowCount()):
        item = dlg._table.item(row, 0)
        out[item.data(Qt.UserRole)] = item
    return out


def test_lists_remote_branches_excluding_head(qtbot):
    dlg, _, _ = _make(qtbot)
    names = set(_rows_by_name(dlg))
    assert names == {"origin/feature-a", "origin/feature-b", "origin/main"}


def test_default_branch_not_checkable(qtbot):
    dlg, _, _ = _make(qtbot)
    rows = _rows_by_name(dlg)
    assert not (rows["origin/main"].flags() & Qt.ItemIsUserCheckable)
    assert rows["origin/feature-a"].flags() & Qt.ItemIsUserCheckable


def test_select_all_skips_default_and_counts(qtbot):
    dlg, _, _ = _make(qtbot)
    dlg._select_all_visible()
    assert set(dlg._collect_selected()) == {"origin/feature-a", "origin/feature-b"}
    assert dlg._delete_btn.text() == "Delete Selected (2)"


def test_filter_hides_non_matching(qtbot):
    dlg, _, _ = _make(qtbot)
    dlg._apply_filter("feature-a")
    rows = _rows_by_name(dlg)
    hidden = {
        n: dlg._table.isRowHidden(r)
        for r in range(dlg._table.rowCount())
        for n in [dlg._table.item(r, 0).data(Qt.UserRole)]
    }
    assert hidden["origin/feature-a"] is False
    assert hidden["origin/feature-b"] is True


def test_grouped_by_remote():
    grouped = RemoteBranchesDialog._grouped_by_remote(["origin/a", "origin/b", "upstream/c"])
    assert grouped == {"origin": ["a", "b"], "upstream": ["c"]}


def test_perform_deletions_one_call_per_remote(qtbot):
    dlg, _, commands = _make(qtbot)
    commands.delete_remote_branches.execute.side_effect = lambda remote, br: [
        RemoteBranchDeleteResult(f"{remote}/{b}", True, "deleted") for b in br
    ]
    results = dlg._perform_deletions({"origin": ["a", "b"], "upstream": ["c"]})
    assert commands.delete_remote_branches.execute.call_count == 2
    assert {r.branch for r in results} == {"origin/a", "origin/b", "upstream/c"}


def test_on_delete_cancel_does_nothing(qtbot):
    dlg, _, commands = _make(qtbot)
    dlg._select_all_visible()
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Cancel):
        dlg._on_delete()
    commands.delete_remote_branches.execute.assert_not_called()


def test_on_delete_confirm_runs_and_refreshes(qtbot):
    dlg, queries, commands = _make(qtbot)
    commands.delete_remote_branches.execute.side_effect = lambda remote, br: [
        RemoteBranchDeleteResult(f"{remote}/{b}", True, "deleted") for b in br
    ]
    dlg._select_all_visible()

    class _SyncThread:
        def __init__(self, target=None, daemon=None):
            self._t = target

        def start(self):
            self._t()

    with (
        patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
        patch.object(QMessageBox, "information"),
        patch("git_gui.presentation.dialogs.remote_branches_dialog.threading.Thread", _SyncThread),
    ):
        dlg._on_delete()

    assert commands.delete_remote_branches.execute.call_count == 1
    # refresh re-queried branches (called twice: initial + after delete)
    assert queries.get_branches.execute.call_count >= 2
