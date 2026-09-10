"""Tests for narrowing the diff panel to the file whose history is showing."""

from __future__ import annotations

from unittest.mock import MagicMock

from PySide6.QtWidgets import QWidget

from git_gui.domain.entities import FileStatus
from git_gui.presentation.widgets.diff import DiffWidget


def _fs(path: str) -> FileStatus:
    return FileStatus(path=path, status="staged", delta="modified")


def _make_widget(qtbot) -> DiffWidget:
    w = DiffWidget.__new__(DiffWidget)
    QWidget.__init__(w)
    w._path_filter = None
    w._current_oid = None
    qtbot.addWidget(w)
    return w


def test_no_filter_keeps_every_file(qtbot):
    w = _make_widget(qtbot)
    files = [_fs("a.py"), _fs("b.py")]
    assert w._apply_path_filter(files) == files


def test_filter_narrows_to_the_one_file(qtbot):
    w = _make_widget(qtbot)
    w._path_filter = "b.py"
    assert [f.path for f in w._apply_path_filter([_fs("a.py"), _fs("b.py")])] == ["b.py"]


def test_commit_without_the_path_falls_back_to_all_files(qtbot):
    """History followed across a rename reaches commits using the old name.

    Matching nothing there would leave an empty panel that looks broken, so
    those commits show their full file list instead.
    """
    w = _make_widget(qtbot)
    w._path_filter = "renamed.py"
    files = [_fs("original.py"), _fs("other.py")]
    assert w._apply_path_filter(files) == files


def test_set_path_filter_reloads_the_current_commit(qtbot):
    w = _make_widget(qtbot)
    w._current_oid = "deadbeef"
    w.load_commit = MagicMock()

    w.set_path_filter("b.py")

    w.load_commit.assert_called_once_with("deadbeef")


def test_set_path_filter_is_a_noop_when_unchanged(qtbot):
    w = _make_widget(qtbot)
    w._path_filter = "b.py"
    w._current_oid = "deadbeef"
    w.load_commit = MagicMock()

    w.set_path_filter("b.py")

    w.load_commit.assert_not_called()


def test_clearing_the_filter_with_no_commit_loaded_does_not_reload(qtbot):
    w = _make_widget(qtbot)
    w._path_filter = "b.py"
    w.load_commit = MagicMock()

    w.set_path_filter(None)

    assert w._path_filter is None
    w.load_commit.assert_not_called()
