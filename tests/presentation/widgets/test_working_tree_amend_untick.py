"""Amend unticked by the app, not the user, still hands the draft back."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from git_gui.presentation.widgets.working_tree import WorkingTreeWidget


@pytest.fixture
def amending(qtbot):
    """A panel with 'my draft' typed and Amend ticked over HEAD's 'Fix typo'."""
    queries, commands = MagicMock(), MagicMock()
    queries.get_identity.execute.return_value = ("Alice", "alice@example.com")
    queries.get_head_oid.execute.return_value = "deadbeef"
    queries.get_commit_detail.execute.return_value = SimpleNamespace(message="Fix typo")
    w = WorkingTreeWidget(queries, commands)
    qtbot.addWidget(w)
    w._msg_edit.setPlainText("my draft")
    w._chk_amend.setChecked(True)
    assert w._msg_edit.toPlainText() == "Fix typo"
    return w


def test_a_merge_starting_under_amend_keeps_the_finish_merge_label(amending):
    amending.update_conflict_banner("MERGING", "Merge branch 'feature'")

    assert amending._btn_commit.text() == "Finish Merge"


def test_a_merge_starting_under_amend_does_not_reuse_heads_message(amending):
    continued: list[str] = []
    amending.merge_continue_requested.connect(continued.append)

    amending.update_conflict_banner("MERGING", "Merge branch 'feature'")
    amending._on_commit()

    assert continued == ["my draft"]


def test_a_rebase_starting_under_amend_keeps_its_label(amending):
    amending.update_conflict_banner("REBASING")

    assert amending._btn_commit.text() == "Continue Rebase"
    assert amending._msg_edit.toPlainText() == "my draft"
