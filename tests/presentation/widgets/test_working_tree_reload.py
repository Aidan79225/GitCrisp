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


# ── An auto-reload keeps the file the user is reading ────────────────────────


def _select_then_reload(qtbot, w, queries, after: list[FileStatus]) -> None:
    """Select a.txt, then reload onto *after*, whose b.txt is staged so the
    refill can be told apart from the list it replaces."""
    _load(
        qtbot,
        w,
        queries,
        [_fs("a.txt", StagingState.UNSTAGED), _fs("b.txt", StagingState.UNSTAGED)],
    )
    w._file_view.setCurrentIndex(w._file_model.index(0))
    assert w._hunk_diff._current_path == "a.txt"
    queries.get_working_tree.execute.return_value = after
    w.reload()
    qtbot.waitUntil(lambda: ("b.txt", StagingState.STAGED) in _listed(w), timeout=2000)


def test_a_reload_keeps_the_selected_file_selected(qtbot, panel):
    w, queries = panel
    _select_then_reload(
        qtbot,
        w,
        queries,
        [_fs("a.txt", StagingState.UNSTAGED), _fs("b.txt", StagingState.STAGED)],
    )

    current = w._file_view.currentIndex()
    assert current.isValid()
    assert w._file_model.data(current, Qt.UserRole).path == "a.txt"
    assert w._hunk_diff._current_path == "a.txt"


def test_a_reload_falls_back_to_all_files_when_the_selected_file_is_gone(qtbot, panel):
    w, queries = panel
    _select_then_reload(qtbot, w, queries, [_fs("b.txt", StagingState.STAGED)])

    assert not w._file_view.currentIndex().isValid()
    assert w._hunk_diff._all_paths == ["b.txt"]


# ── A repo switch drops whatever the old repo still has in flight ────────────


def test_a_late_status_from_the_old_repo_does_not_fill_the_new_repos_list(qtbot, panel):
    import threading

    w, old_queries = panel
    release = threading.Event()

    def _slow_status():
        release.wait(timeout=5)
        return [_fs("only_in_A.txt", StagingState.UNSTAGED)]

    old_queries.get_working_tree.execute.side_effect = _slow_status
    w.reload()

    new_queries, new_commands = MagicMock(), MagicMock()
    new_queries.get_working_tree_diff_map.execute.return_value = {}
    new_queries.list_submodules.execute.return_value = []
    w.set_buses(new_queries, new_commands)
    _load(qtbot, w, new_queries, [_fs("only_in_B.txt", StagingState.UNSTAGED)])

    release.set()
    qtbot.wait(200)

    assert _listed(w) == [("only_in_B.txt", StagingState.UNSTAGED)]


def test_a_repo_switch_empties_the_list_until_the_new_repo_loads(qtbot, panel):
    w, queries = panel
    _load(qtbot, w, queries, [_fs("a.txt", StagingState.UNSTAGED)])

    w.set_buses(MagicMock(), MagicMock())

    assert _listed(w) == []
