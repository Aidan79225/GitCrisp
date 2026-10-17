"""How the working-tree list refills after a reload or a stage."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt

from git_gui.domain.entities import FileDelta, FileStatus, StagingState
from git_gui.presentation.widgets.working_tree import WorkingTreeWidget


def _fs(path: str, status: StagingState) -> FileStatus:
    return FileStatus(path=path, status=status, delta=FileDelta.MODIFIED)


def _listed(w: WorkingTreeWidget) -> list[tuple[str, StagingState]]:
    model = w._file_model
    rows = (model.data(model.index(row), Qt.UserRole) for row in range(model.rowCount()))
    return [(fs.path, fs.status) for fs in rows]


@pytest.fixture
def panel(qtbot):
    queries, commands = MagicMock(), MagicMock()
    queries.get_working_tree_diff_map.execute.return_value = {}
    queries.get_staged_diff.execute.return_value = []
    queries.get_file_diff.execute.return_value = []
    queries.list_submodules.execute.return_value = []
    w = WorkingTreeWidget(queries, commands)
    qtbot.addWidget(w)
    return w, queries


def _load(qtbot, w, queries, files: list[FileStatus]) -> None:
    queries.get_working_tree.execute.return_value = files
    w.reload()
    expected = [(f.path, f.status) for f in files]
    qtbot.waitUntil(lambda: sorted(_listed(w)) == sorted(expected), timeout=2000)


# ── Conflicts first, however the list was refilled ───────────────────────────


def test_staging_a_file_does_not_move_the_conflict_off_the_top(qtbot, panel):
    w, queries = panel
    _load(
        qtbot,
        w,
        queries,
        [
            _fs("a.txt", StagingState.UNSTAGED),
            _fs("b.txt", StagingState.UNSTAGED),
            _fs("z.txt", StagingState.CONFLICTED),
        ],
    )
    queries.get_working_tree.execute.return_value = [
        _fs("a.txt", StagingState.STAGED),
        _fs("b.txt", StagingState.UNSTAGED),
        _fs("z.txt", StagingState.CONFLICTED),
    ]

    w._file_model.setData(w._file_model.index(1), Qt.CheckState.Checked, Qt.CheckStateRole)
    qtbot.waitUntil(lambda: ("a.txt", StagingState.STAGED) in _listed(w), timeout=2000)

    assert [path for path, _ in _listed(w)] == ["z.txt", "a.txt", "b.txt"]


def test_the_diff_blocks_follow_the_order_of_the_list(qtbot, panel):
    w, queries = panel
    _load(
        qtbot,
        w,
        queries,
        [_fs("a.txt", StagingState.UNSTAGED), _fs("z.txt", StagingState.CONFLICTED)],
    )

    assert w._hunk_diff._all_paths == ["z.txt", "a.txt"]
