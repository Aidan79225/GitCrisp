"""The commit message's chevron after a new commit is loaded."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt

from git_gui.domain.entities import Commit
from git_gui.presentation.widgets.diff import DiffWidget


def _widget(qtbot) -> DiffWidget:
    queries = MagicMock()
    queries.get_commit_detail.execute.return_value = Commit(
        oid="a" * 40,
        message="Subject\n",
        author="Alice",
        timestamp=datetime(2026, 1, 1),
        parents=[],
    )
    queries.get_branches.execute.return_value = []
    queries.get_commit_files.execute.return_value = []
    queries.list_submodules.execute.return_value = []
    widget = DiffWidget(queries, MagicMock())
    qtbot.addWidget(widget)
    widget.show()
    return widget


def test_loading_a_commit_reexpands_the_message_and_names_the_chevron_for_it(qtbot):
    """load_commit set the arrow by hand and left the spoken name saying
    "Expand" over a message that was already expanded."""
    widget = _widget(qtbot)
    widget._msg_toggle.click()  # collapse
    assert widget._msg_toggle.accessibleName() == "Expand"

    with patch("threading.Thread"):
        widget.load_commit("a" * 40)

    assert widget._msg_toggle.is_expanded()
    assert widget._msg_toggle.arrowType() == Qt.DownArrow
    assert widget._msg_toggle.accessibleName() == "Collapse"
