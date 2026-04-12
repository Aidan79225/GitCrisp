"""Tests for keyboard shortcuts: Ctrl+F search, Ctrl+W close repo, Ctrl+1-9 switch repo."""
from __future__ import annotations
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt

from git_gui.domain.entities import Commit
from git_gui.presentation.widgets.graph import _SearchBar, GraphWidget


# ── helpers ──────────────────────────────────────────────────────────────────


def _commit(oid="abc", msg="Initial commit", author="Alice <a@a.com>",
            ts=None, parents=None):
    return Commit(oid=oid, message=msg, author=author,
                  timestamp=ts or datetime(2026, 1, 15, 10, 30),
                  parents=parents or [])


def _fake_buses():
    queries = MagicMock()
    queries.get_commit_graph.execute.return_value = []
    queries.get_branches.execute.return_value = []
    queries.get_tags.execute.return_value = []
    queries.is_dirty.execute.return_value = False
    queries.get_head_oid.execute.return_value = "abc"
    commands = MagicMock()
    return queries, commands


# ── _SearchBar unit tests ────────────────────────────────────────────────────


class TestSearchBar:
    def test_initially_hidden(self, qtbot):
        bar = _SearchBar()
        qtbot.addWidget(bar)
        assert not bar.isVisible()

    def test_open_shows_bar(self, qtbot):
        bar = _SearchBar()
        qtbot.addWidget(bar)
        bar.show()
        bar.open()
        assert bar.isVisible()

    def test_close_hides_and_clears(self, qtbot):
        bar = _SearchBar()
        qtbot.addWidget(bar)
        bar.show()
        bar.open()
        bar.input_widget.setText("query")
        bar.close_bar()
        assert not bar.isVisible()
        assert bar.text() == ""

    def test_match_label_format(self, qtbot):
        bar = _SearchBar()
        qtbot.addWidget(bar)
        bar.set_match_label(2, 10)
        assert bar._label.text() == "3 / 10"

    def test_match_label_zero(self, qtbot):
        bar = _SearchBar()
        qtbot.addWidget(bar)
        bar.set_match_label(0, 0)
        assert bar._label.text() == "0 / 0"

    def test_enter_emits_navigate_next(self, qtbot):
        bar = _SearchBar()
        qtbot.addWidget(bar)
        bar.open()
        with qtbot.waitSignal(bar.navigate_requested, timeout=1000) as blocker:
            bar.input_widget.returnPressed.emit()
        assert blocker.args == [1]


# ── GraphWidget search integration ───────────────────────────────────────────


class TestGraphSearch:
    def _make_widget(self, qtbot, commits, refs=None):
        queries, commands = _fake_buses()
        w = GraphWidget(queries, commands)
        qtbot.addWidget(w)
        w._model.reload(commits, refs or {})
        w._has_more = False  # all commits are pre-loaded in tests
        return w

    def test_open_search_shows_bar(self, qtbot):
        w = self._make_widget(qtbot, [])
        w.show()
        w.open_search()
        assert w._search_bar.isVisible()

    def test_close_search_hides_bar(self, qtbot):
        w = self._make_widget(qtbot, [])
        w.show()
        w.open_search()
        w._close_search()
        assert not w._search_bar.isVisible()

    def test_close_search_clears_matches(self, qtbot):
        commits = [_commit("a1", msg="feat: login")]
        w = self._make_widget(qtbot, commits)
        w._search_bar.input_widget.setText("login")
        assert len(w._search_matches) == 1
        w._close_search()
        assert w._search_matches == []
        assert w._search_idx == -1

    def test_search_by_message(self, qtbot):
        commits = [
            _commit("a1", msg="feat: add login"),
            _commit("a2", msg="fix: typo in readme"),
            _commit("a3", msg="feat: add logout"),
        ]
        w = self._make_widget(qtbot, commits)
        w._search_bar.input_widget.setText("login")
        assert len(w._search_matches) == 1
        assert w._search_matches[0] == 0

    def test_search_by_author(self, qtbot):
        commits = [
            _commit("a1", author="Alice <alice@x.com>"),
            _commit("a2", author="Bob <bob@x.com>"),
        ]
        w = self._make_widget(qtbot, commits)
        w._search_bar.input_widget.setText("bob")
        assert w._search_matches == [1]

    def test_search_by_oid(self, qtbot):
        commits = [
            _commit("deadbeef12345678"),
            _commit("cafebabe87654321"),
        ]
        w = self._make_widget(qtbot, commits)
        w._search_bar.input_widget.setText("cafebabe")
        assert w._search_matches == [1]

    def test_search_by_date(self, qtbot):
        commits = [
            _commit("a1", ts=datetime(2026, 1, 15, 10, 0)),
            _commit("a2", ts=datetime(2026, 3, 20, 14, 0)),
        ]
        w = self._make_widget(qtbot, commits)
        w._search_bar.input_widget.setText("2026-03")
        assert w._search_matches == [1]

    def test_search_multiple_matches(self, qtbot):
        commits = [
            _commit("a1", msg="feat: add thing"),
            _commit("a2", msg="docs: update"),
            _commit("a3", msg="feat: add other"),
        ]
        w = self._make_widget(qtbot, commits)
        w._search_bar.input_widget.setText("feat")
        assert w._search_matches == [0, 2]

    def test_search_navigate_next_wraps(self, qtbot):
        commits = [
            _commit("a1", msg="feat: X"),
            _commit("a2", msg="fix: Y"),
            _commit("a3", msg="feat: Z"),
        ]
        w = self._make_widget(qtbot, commits)
        w._search_bar.input_widget.setText("feat")
        assert w._search_idx == 0
        w._on_search_navigate(1)
        assert w._search_idx == 1
        w._on_search_navigate(1)  # wraps to 0
        assert w._search_idx == 0

    def test_search_navigate_prev_wraps(self, qtbot):
        commits = [
            _commit("a1", msg="feat: X"),
            _commit("a2", msg="feat: Y"),
        ]
        w = self._make_widget(qtbot, commits)
        w._search_bar.input_widget.setText("feat")
        assert w._search_idx == 0
        w._on_search_navigate(-1)  # prev wraps to last
        assert w._search_idx == 1

    def test_search_case_insensitive(self, qtbot):
        commits = [_commit("a1", msg="FIX: Big Bug")]
        w = self._make_widget(qtbot, commits)
        w._search_bar.input_widget.setText("big bug")
        assert w._search_matches == [0]

    def test_search_empty_text_clears(self, qtbot):
        commits = [_commit("a1", msg="feat")]
        w = self._make_widget(qtbot, commits)
        w._search_bar.input_widget.setText("feat")
        assert len(w._search_matches) == 1
        w._search_bar.input_widget.setText("")
        assert w._search_matches == []

    def test_search_no_match(self, qtbot):
        commits = [_commit("a1", msg="hello")]
        w = self._make_widget(qtbot, commits)
        w._search_bar.input_widget.setText("zzzzz")
        assert w._search_matches == []
        assert w._search_idx == -1

    def test_search_match_label_updates(self, qtbot):
        commits = [
            _commit("a1", msg="feat: X"),
            _commit("a2", msg="feat: Y"),
            _commit("a3", msg="feat: Z"),
        ]
        w = self._make_widget(qtbot, commits)
        w._search_bar.input_widget.setText("feat")
        assert w._search_bar._label.text() == "1 / 3"
        w._on_search_navigate(1)
        assert w._search_bar._label.text() == "2 / 3"


# ── MainWindow close / switch logic ─────────────────────────────────────────
# We test the method logic by calling the unbound methods on a mock object
# that has the required attributes, avoiding full MainWindow construction.


def _make_main_window_stub(repo_path, open_repos):
    """Create a lightweight stub with attributes needed by _close_current_repo
    and _switch_to_repo_index."""
    stub = MagicMock()
    stub._repo_path = repo_path
    store = MagicMock()
    store.get_open_repos.return_value = list(open_repos)
    stub._repo_store = store
    return stub


class TestCloseCurrentRepoLogic:
    def test_close_delegates_to_on_repo_close(self):
        from git_gui.presentation.main_window import MainWindow
        stub = _make_main_window_stub("/repo/a", ["/repo/a"])
        MainWindow._close_current_repo(stub)
        stub._on_repo_close.assert_called_once_with("/repo/a")

    def test_close_noop_without_repo(self):
        from git_gui.presentation.main_window import MainWindow
        stub = _make_main_window_stub(None, [])
        MainWindow._close_current_repo(stub)
        stub._on_repo_close.assert_not_called()


class TestSwitchToRepoIndexLogic:
    def test_switch_to_valid_index(self):
        from git_gui.presentation.main_window import MainWindow
        stub = _make_main_window_stub("/repo/a", ["/repo/a", "/repo/b", "/repo/c"])
        MainWindow._switch_to_repo_index(stub, 2)
        stub._switch_repo.assert_called_once_with("/repo/b")

    def test_switch_to_out_of_range(self):
        from git_gui.presentation.main_window import MainWindow
        stub = _make_main_window_stub("/repo/a", ["/repo/a"])
        MainWindow._switch_to_repo_index(stub, 5)
        stub._switch_repo.assert_not_called()

    def test_switch_to_current_repo_noop(self):
        from git_gui.presentation.main_window import MainWindow
        stub = _make_main_window_stub("/repo/a", ["/repo/a", "/repo/b"])
        MainWindow._switch_to_repo_index(stub, 1)  # /repo/a is already active
        stub._switch_repo.assert_not_called()

    def test_switch_to_third_repo(self):
        from git_gui.presentation.main_window import MainWindow
        stub = _make_main_window_stub("/repo/a", ["/repo/a", "/repo/b", "/repo/c"])
        MainWindow._switch_to_repo_index(stub, 3)
        stub._switch_repo.assert_called_once_with("/repo/c")
