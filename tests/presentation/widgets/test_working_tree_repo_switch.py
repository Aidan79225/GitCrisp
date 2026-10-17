"""What the working-tree panel forgets when the repo under it changes."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from git_gui.presentation.widgets.working_tree import WorkingTreeWidget


def _buses():
    queries, commands = MagicMock(), MagicMock()
    queries.get_identity.execute.return_value = ("Alice", "alice@example.com")
    return queries, commands


@pytest.fixture
def widget(qtbot):
    w = WorkingTreeWidget(*_buses())
    qtbot.addWidget(w)
    return w


def test_a_merge_in_the_old_repo_does_not_follow_into_the_new_one(widget):
    widget.update_conflict_banner("MERGING", "Merge branch 'feature'")

    widget.set_buses(*_buses())

    assert not widget._conflict_banner.isVisibleTo(widget)
    assert widget._btn_commit.text() == "Commit"
    assert widget._chk_amend.isEnabled()


def test_the_old_repos_message_is_not_committed_in_the_new_one(widget):
    widget.update_conflict_banner("MERGING", "Merge branch 'feature'")

    widget.set_buses(*_buses())

    assert widget._msg_edit.toPlainText() == ""


def test_commit_after_a_switch_creates_a_commit_instead_of_finishing_the_old_merge(widget):
    widget.update_conflict_banner("MERGING", "Merge branch 'feature'")
    queries, commands = _buses()
    widget.set_buses(queries, commands)
    continued: list[str] = []
    widget.merge_continue_requested.connect(continued.append)

    widget._msg_edit.setPlainText("Fix typo")
    widget._on_commit()

    assert continued == []
    commands.create_commit.execute.assert_called_once_with("Fix typo")
