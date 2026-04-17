"""Integration tests for DiffWidget lazy loading flow."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from git_gui.domain.entities import Branch, Commit, FileStatus
from git_gui.presentation.widgets.diff import DiffWidget


def _make_mock_queries():
    """Build a MagicMock that satisfies every QueryBus attribute DiffWidget touches."""
    queries = MagicMock()

    # get_commit_detail.execute(oid) -> Commit
    queries.get_commit_detail.execute.return_value = Commit(
        oid="abc123",
        message="Initial commit\n",
        author="Test Author",
        timestamp=datetime(2025, 1, 1),
        parents=[],
    )

    # get_branches.execute() -> list[Branch]
    queries.get_branches.execute.return_value = [
        Branch(name="main", is_remote=False, is_head=True, target_oid="abc123"),
    ]

    # get_commit_files.execute(oid) -> list[FileStatus]
    queries.get_commit_files.execute.return_value = [
        FileStatus(path="hello.py", status="staged", delta="added"),
    ]

    # list_submodules.execute() -> []
    queries.list_submodules.execute.return_value = []

    # get_commit_diff_map.execute(oid) -> dict  (background thread)
    queries.get_commit_diff_map.execute.return_value = {}

    return queries


@pytest.fixture
def diff_widget(qtbot):
    queries = _make_mock_queries()
    commands = MagicMock()
    widget = DiffWidget(queries, commands)
    qtbot.addWidget(widget)
    widget.show()
    return widget, queries


# ── 1. load_commit shows panels ───────────────────────────────────────


def test_load_commit_shows_panels(diff_widget, qtbot):
    """After a successful load_commit, detail/message/splitter are visible."""
    widget, queries = diff_widget

    # Patch Thread so _render_all_files doesn't spawn a real thread
    with patch("threading.Thread"):
        widget.load_commit("abc123")

    assert widget._detail.isVisible()
    assert widget._msg_view.isVisible()
    assert widget._splitter.isVisible()


# ── 2. load_commit error hides panels ─────────────────────────────────


def test_load_commit_error_hides_panels(diff_widget, qtbot):
    """When get_commit_detail raises, the widget enters empty state."""
    widget, queries = diff_widget

    queries.get_commit_detail.execute.side_effect = RuntimeError("gone")

    widget.load_commit("bad_oid")

    assert not widget._detail.isVisible()
    assert not widget._msg_view.isVisible()
    assert not widget._splitter.isVisible()


# ── 3. set_buses(None, None) enters empty state ──────────────────────


def test_set_buses_none_enters_empty_state(diff_widget, qtbot):
    """Calling set_buses(None, None) hides all panels."""
    widget, queries = diff_widget

    # First show panels so we can verify they get hidden
    with patch("threading.Thread"):
        widget.load_commit("abc123")
    assert widget._splitter.isVisible()

    widget.set_buses(None, None)

    assert not widget._detail.isVisible()
    assert not widget._msg_view.isVisible()
    assert not widget._splitter.isVisible()


# ── 4. _clear_blocks clears loader ───────────────────────────────────


def test_clear_blocks_clears_loader(diff_widget, qtbot):
    """_clear_blocks() empties the loader's block_refs list."""
    widget, queries = diff_widget

    # Populate blocks via load_commit
    with patch("threading.Thread"):
        widget.load_commit("abc123")

    # Loader should have block refs from _render_all_files
    assert widget._loader is not None
    assert len(widget._loader._block_refs) > 0

    widget._clear_blocks()

    assert widget._loader._block_refs == []
    assert widget._loader._loaded_paths == set()
    assert widget._loader._diff_map == {}


# ── 5. Collapsing header wiring ──────────────────────────────────────


def test_on_diff_scrolled_sets_progress_from_scroll_value(diff_widget, qtbot):
    """Scrolling the diff area updates the header collapse progress."""
    widget, _ = diff_widget

    with patch("threading.Thread"):
        widget.load_commit("abc123")

    expanded = widget._header.expanded_height()
    assert expanded > 0  # sanity: mock commit has a message, so expanded > 0

    widget._on_diff_scrolled(expanded // 2)

    p = widget._header.collapse_progress()
    assert 0.45 <= p <= 0.55


def test_on_diff_scrolled_clamps_past_expanded_height(diff_widget, qtbot):
    """Scrolling past the expanded header height pins progress at 1.0."""
    widget, _ = diff_widget

    with patch("threading.Thread"):
        widget.load_commit("abc123")

    expanded = widget._header.expanded_height()
    widget._on_diff_scrolled(expanded * 3)

    assert widget._header.collapse_progress() == 1.0


def test_load_commit_resets_collapse_progress(diff_widget, qtbot):
    """A commit reload puts the header back to fully-expanded state."""
    widget, _ = diff_widget

    with patch("threading.Thread"):
        widget.load_commit("abc123")

    widget._header.set_collapse_progress(0.8)
    assert widget._header.collapse_progress() == 0.8

    with patch("threading.Thread"):
        widget.load_commit("abc123")

    assert widget._header.collapse_progress() == 0.0


def test_load_commit_error_resets_collapse_progress(diff_widget, qtbot):
    """A failed commit load also puts the header back to progress 0."""
    widget, queries = diff_widget

    with patch("threading.Thread"):
        widget.load_commit("abc123")
    widget._header.set_collapse_progress(0.7)

    queries.get_commit_detail.execute.side_effect = RuntimeError("gone")
    widget.load_commit("bad_oid")

    assert widget._header.collapse_progress() == 0.0


def test_scrollbar_valueChanged_drives_handler(diff_widget, qtbot):
    """The signal from the diff scroll bar is connected to the handler —
    emitting it updates collapse progress without a direct call."""
    widget, _ = diff_widget

    with patch("threading.Thread"):
        widget.load_commit("abc123")

    expanded = widget._header.expanded_height()
    widget._diff_scroll.verticalScrollBar().valueChanged.emit(expanded)

    assert widget._header.collapse_progress() == 1.0


def test_on_diff_scrolled_zero_keeps_progress_expanded(diff_widget, qtbot):
    """Scrolling back to the top re-expands the header (progress 0.0)."""
    widget, _ = diff_widget

    with patch("threading.Thread"):
        widget.load_commit("abc123")

    widget._header.set_collapse_progress(0.6)
    widget._on_diff_scrolled(0)

    assert widget._header.collapse_progress() == 0.0
