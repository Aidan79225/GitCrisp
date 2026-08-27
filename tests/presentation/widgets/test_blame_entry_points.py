"""Tests for reaching blame from a file, and for what a blame click drives."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from git_gui.presentation.main_window.right_panel import RightPanelMixin


class _Host(RightPanelMixin):
    """Bare composite standing in for MainWindow's attributes."""

    def __init__(self) -> None:
        self._queries = MagicMock()
        self._graph = MagicMock()
        self._blame_windows: dict = {}


@pytest.fixture
def host():
    return _Host()


class _FakeMenu:
    """Stand-in for QMenu that reports a chosen action without showing anything.

    PySide6 types reject attribute patching, so each widget module's own QMenu
    name is swapped instead.
    """

    choice = ""

    def __init__(self, *_a, **_k) -> None:
        self._actions: dict[str, object] = {}

    def addAction(self, text: str):
        self._actions[text] = object()  # identity is what the callers compare
        return self._actions[text]

    def addSeparator(self) -> None:
        pass

    def exec(self, *_a, **_k):
        return self._actions.get(_FakeMenu.choice)


def _choosing(module: str, label: str):
    _FakeMenu.choice = label
    return patch(f"{module}.QMenu", _FakeMenu)


# ── Menu entries ─────────────────────────────────────────────────────────────


def test_working_tree_menu_blames_head(qtbot):
    """A working-tree file has no revision of its own — blame the last commit."""
    from git_gui.presentation.widgets.working_tree import WorkingTreeWidget

    w = WorkingTreeWidget.__new__(WorkingTreeWidget)
    from PySide6.QtWidgets import QWidget

    QWidget.__init__(w)
    qtbot.addWidget(w)
    w._file_view = MagicMock()
    w._file_model = MagicMock()
    w._file_model.data.return_value = MagicMock(path="src/app.py")
    w._file_view.indexAt.return_value = MagicMock(isValid=lambda: True)

    got: list[tuple] = []
    w.blame_requested.connect(lambda p, o: got.append((p, o)))
    with _choosing("git_gui.presentation.widgets.working_tree", "Blame this file"):
        w._on_file_context_menu(MagicMock())

    assert got == [("src/app.py", None)]


def test_diff_panel_menu_blames_the_commit_on_screen(qtbot):
    """Asking for blame while reading an old commit asks about *then*, not HEAD."""
    from PySide6.QtWidgets import QWidget

    from git_gui.presentation.widgets.diff import DiffWidget

    w = DiffWidget.__new__(DiffWidget)
    QWidget.__init__(w)
    qtbot.addWidget(w)
    w._current_oid = "deadbeef"

    got: list[tuple] = []
    w.blame_requested.connect(lambda p, o: got.append((p, o)))
    with _choosing("git_gui.presentation.widgets.diff", "Blame this file"):
        w._show_file_header_menu(MagicMock(), "src/app.py")

    assert got == [("src/app.py", "deadbeef")]


def test_file_navigator_menu_emits_the_path(qtbot):
    from PySide6.QtWidgets import QWidget

    from git_gui.presentation.widgets.file_navigator import FileNavigatorWidget

    w = FileNavigatorWidget.__new__(FileNavigatorWidget)
    QWidget.__init__(w)
    qtbot.addWidget(w)

    got: list[str] = []
    w.blame_requested.connect(got.append)
    with _choosing("git_gui.presentation.widgets.file_navigator", "Blame this file"):
        w._show_file_menu(MagicMock(), "src/app.py")

    assert got == ["src/app.py"]


def test_file_history_still_fires_from_every_menu(qtbot):
    """The three menus grew a second entry; the first must still work."""
    from PySide6.QtWidgets import QWidget

    from git_gui.presentation.widgets.diff import DiffWidget
    from git_gui.presentation.widgets.file_navigator import FileNavigatorWidget
    from git_gui.presentation.widgets.working_tree import WorkingTreeWidget

    wt = WorkingTreeWidget.__new__(WorkingTreeWidget)
    QWidget.__init__(wt)
    wt._file_view = MagicMock()
    wt._file_model = MagicMock()
    wt._file_model.data.return_value = MagicMock(path="src/app.py")
    wt._file_view.indexAt.return_value = MagicMock(isValid=lambda: True)

    diff = DiffWidget.__new__(DiffWidget)
    QWidget.__init__(diff)
    diff._current_oid = "deadbeef"

    nav = FileNavigatorWidget.__new__(FileNavigatorWidget)
    QWidget.__init__(nav)
    for widget in (wt, diff, nav):
        qtbot.addWidget(widget)

    got: list[str] = []
    for widget in (wt, diff, nav):
        widget.file_history_requested.connect(got.append)

    label = "Show file history"
    with _choosing("git_gui.presentation.widgets.working_tree", label):
        wt._on_file_context_menu(MagicMock())
    with _choosing("git_gui.presentation.widgets.diff", label):
        diff._show_file_header_menu(MagicMock(), "src/app.py")
    with _choosing("git_gui.presentation.widgets.file_navigator", label):
        nav._show_file_menu(MagicMock(), "src/app.py")

    assert got == ["src/app.py"] * 3


# ── Window lifecycle ─────────────────────────────────────────────────────────


def test_opening_blame_creates_one_window(host, qtbot):
    with patch("git_gui.presentation.main_window.right_panel.BlameWindow") as factory:
        host._on_blame_requested("src/app.py", None)

    factory.assert_called_once_with(host._queries, "src/app.py", None)
    assert list(host._blame_windows) == [("src/app.py", None)]


def test_reopening_the_same_file_raises_rather_than_duplicates(host, qtbot):
    with patch("git_gui.presentation.main_window.right_panel.BlameWindow") as factory:
        host._on_blame_requested("src/app.py", None)
        host._on_blame_requested("src/app.py", None)

    assert factory.call_count == 1
    factory.return_value.raise_.assert_called_once()
    factory.return_value.activateWindow.assert_called_once()


def test_a_different_revision_is_a_separate_window(host, qtbot):
    """Blaming a file at HEAD and at an old commit are two different questions."""
    with patch("git_gui.presentation.main_window.right_panel.BlameWindow"):
        host._on_blame_requested("src/app.py", None)
        host._on_blame_requested("src/app.py", "deadbeef")

    assert set(host._blame_windows) == {("src/app.py", None), ("src/app.py", "deadbeef")}


def test_nothing_opens_without_a_repo(host, qtbot):
    host._queries = None
    with patch("git_gui.presentation.main_window.right_panel.BlameWindow") as factory:
        host._on_blame_requested("src/app.py", None)

    factory.assert_not_called()
    assert host._blame_windows == {}


def test_switching_repo_closes_every_blame_window(host, qtbot):
    """The windows show files from the repo being left behind."""
    with patch("git_gui.presentation.main_window.right_panel.BlameWindow") as factory:
        host._on_blame_requested("a.py", None)
        host._on_blame_requested("b.py", None)
        windows = [factory.return_value]

    host._close_blame_windows()

    assert host._blame_windows == {}
    assert windows[0].close.called


# ── What a click drives ──────────────────────────────────────────────────────


def test_picking_a_line_brings_that_commit_up_in_the_graph(host, qtbot):
    """reload_with_extra_tip, not scroll_to_oid: a blamed commit is often old
    enough to sit beyond the loaded page, and has to be fetched to be shown."""
    host._on_blame_commit_selected("deadbeef")
    host._graph.reload_with_extra_tip.assert_called_once_with("deadbeef")
