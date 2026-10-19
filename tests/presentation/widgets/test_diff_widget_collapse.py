"""Collapsing a file block in the commit view before its diff arrives."""

from __future__ import annotations

import threading
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QPlainTextEdit

from git_gui.domain.entities import Commit, FileStatus, Hunk, LineKind
from git_gui.presentation.widgets._collapse_toggle import _CollapseToggle
from git_gui.presentation.widgets.diff import DiffWidget

_HUNK = Hunk(header="@@ -1,3 +1,3 @@", lines=[(LineKind.ADDED, f"line {i}\n") for i in range(3)])


def _queries_with_gated_diffs(released: threading.Event) -> MagicMock:
    """A query bus for one commit whose diffs arrive only once `released` is set."""
    queries = MagicMock()
    queries.get_commit_detail.execute.return_value = Commit(
        oid="abc123", message="Subject\n", author="A", timestamp=datetime(2025, 1, 1), parents=[]
    )
    queries.get_branches.execute.return_value = []
    queries.get_commit_files.execute.return_value = [
        FileStatus(path="x.txt", status="staged", delta="modified")
    ]
    queries.list_submodules.execute.return_value = []

    def diffs_once_released(_oid: str) -> dict:
        released.wait(5)
        return {"x.txt": [_HUNK]}

    queries.get_commit_diff_map.execute.side_effect = diffs_once_released
    return queries


@pytest.fixture
def gated(qtbot):
    """A shown commit view and the gate holding back its diffs; no gate outlives its test."""
    released = threading.Event()
    widget = DiffWidget(_queries_with_gated_diffs(released), MagicMock())
    qtbot.addWidget(widget)
    widget.resize(800, 500)
    widget.show()
    yield widget, released
    released.set()


def test_a_commit_file_collapsed_before_its_diff_arrives_stays_collapsed(qtbot, gated):
    """The chevron says collapsed, so hunks that arrive later must not show."""
    widget, released = gated
    widget.load_commit("abc123")
    frame = widget._loader._block_refs[0][1]
    toggle = frame.findChild(_CollapseToggle)

    toggle.click()
    released.set()
    qtbot.waitUntil(lambda: bool(frame.findChildren(QPlainTextEdit)), timeout=2000)

    assert not toggle.is_expanded()
    assert not any(editor.isVisible() for editor in frame.findChildren(QPlainTextEdit))
