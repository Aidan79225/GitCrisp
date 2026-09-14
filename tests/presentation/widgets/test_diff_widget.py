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
    """After a successful load_commit, detail/message/scroll_area are visible."""
    widget, queries = diff_widget

    # Patch Thread so _render_all_files doesn't spawn a real thread
    with patch("threading.Thread"):
        widget.load_commit("abc123")

    assert widget._detail.isVisible()
    assert widget._msg_view.isVisible()
    assert widget._scroll_area.isVisible()
    assert widget._file_navigator.isVisible()


# ── 2. load_commit error hides panels ─────────────────────────────────


def test_load_commit_error_hides_panels(diff_widget, qtbot):
    """When get_commit_detail raises, the widget enters empty state."""
    widget, queries = diff_widget

    queries.get_commit_detail.execute.side_effect = RuntimeError("gone")

    widget.load_commit("bad_oid")

    assert not widget._detail.isVisible()
    assert not widget._msg_view.isVisible()
    assert not widget._scroll_area.isVisible()
    assert not widget._file_navigator.isVisible()


# ── 3. set_buses(None, None) enters empty state ──────────────────────


def test_set_buses_none_enters_empty_state(diff_widget, qtbot):
    """Calling set_buses(None, None) hides all panels."""
    widget, queries = diff_widget

    # First show panels so we can verify they get hidden
    with patch("threading.Thread"):
        widget.load_commit("abc123")
    assert widget._scroll_area.isVisible()

    widget.set_buses(None, None)

    assert not widget._detail.isVisible()
    assert not widget._msg_view.isVisible()
    assert not widget._scroll_area.isVisible()
    assert not widget._file_navigator.isVisible()


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


# ── 5. Navigator stays in the scroll flow ────────────────────────────


def test_navigator_scrolls_with_the_diff(diff_widget, qtbot):
    """The file list lives inside the scroll content, so it scrolls away with
    the diff instead of pinning above it."""
    widget, _ = diff_widget
    with patch("threading.Thread"):
        widget.load_commit("abc123")

    assert widget._file_navigator.parent() is widget._scroll_content


# ── 6. Filter change keeps the scroll position ───────────────────────


@pytest.fixture
def multi_file_diff_widget(qtbot):
    """A DiffWidget loaded with three files."""
    queries = _make_mock_queries()
    queries.get_commit_files.execute.return_value = [
        FileStatus(path="a.py", status="staged", delta="modified"),
        FileStatus(path="b.py", status="staged", delta="added"),
        FileStatus(path="c.py", status="staged", delta="deleted"),
    ]
    commands = MagicMock()
    widget = DiffWidget(queries, commands)
    qtbot.addWidget(widget)
    widget.show()
    with patch("threading.Thread"):
        widget.load_commit("abc123")
    widget.adjustSize()
    widget.layout().activate()
    return widget, queries


def test_render_single_file_does_not_call_setvalue(multi_file_diff_widget, qtbot):
    """Filtering to one file leaves the scroll position alone."""
    widget, _ = multi_file_diff_widget

    sb = widget._scroll_area.verticalScrollBar()
    with patch.object(sb, "setValue") as mock_setvalue:
        widget._render_single_file("a.py", [])
        mock_setvalue.assert_not_called()


def test_render_all_files_does_not_call_setvalue(multi_file_diff_widget, qtbot):
    """Returning to all files leaves the scroll position alone."""
    widget, _ = multi_file_diff_widget

    sb = widget._scroll_area.verticalScrollBar()
    with patch.object(sb, "setValue") as mock_setvalue, patch("threading.Thread"):
        widget._render_all_files("abc123")
        mock_setvalue.assert_not_called()


def test_message_collapse_shrinks_msg_view_to_subject_line(diff_widget, qtbot):
    """Toggling the commit message panel to collapsed shrinks _msg_view's
    fixed height down to one line of text plus the document margin.
    Expanding restores the full height that fits the multi-line body."""
    widget, queries = diff_widget

    # Need a multi-line message so collapse vs expand differ visibly.
    # Use an author without <email> to avoid triggering a Gravatar network
    # request that would leave a pending QNetworkReply in the Qt event queue
    # and corrupt subsequent test teardowns.
    from datetime import datetime

    from git_gui.domain.entities import Commit

    multi_line_msg = "Subject line\n\nBody paragraph one.\nBody paragraph two."
    commit = Commit(
        oid="a" * 40,
        message=multi_line_msg,
        author="Alice",
        timestamp=datetime(2026, 5, 8, 12, 0),
        parents=[],
    )
    # Drive load_commit through the underlying queries mock.
    # Patch Thread so _render_all_files doesn't spawn a real background thread —
    # a real thread's cross-thread signal emission can race against teardown.
    queries.get_commit_detail.execute.return_value = commit
    queries.get_branches.execute.return_value = []
    queries.get_commit_files.execute.return_value = []
    queries.get_commit_diff_map.execute.return_value = {}
    with patch("threading.Thread"):
        widget.load_commit(commit.oid)

    full_h = widget._msg_view.height()
    assert full_h > 0

    # Collapse — height shrinks.
    widget._msg_toggle.click()
    collapsed_h = widget._msg_view.height()
    assert collapsed_h < full_h
    # One-line height is roughly fontMetrics().lineSpacing() + margins,
    # which is significantly smaller than four paragraphs.
    line_h = widget._msg_view.fontMetrics().lineSpacing()
    assert collapsed_h < line_h * 2 + 40  # generous upper bound

    # Expand — height returns to full.
    widget._msg_toggle.click()
    assert widget._msg_view.height() == full_h
