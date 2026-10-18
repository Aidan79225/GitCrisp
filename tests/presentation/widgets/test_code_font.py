"""The commit message and the hunks below it share one code font."""

from __future__ import annotations

from git_gui.presentation.widgets.diff import _CommitMessageView
from git_gui.presentation.widgets.diff_block import CODE_FONT_FAMILIES, make_diff_editor


def test_the_commit_message_asks_for_the_same_families_as_the_hunks(qtbot):
    """The message was set in Courier New alone while the hunks under it
    asked for Consolas first, so the two drew in different fonts."""
    message = _CommitMessageView()
    qtbot.addWidget(message)
    editor = make_diff_editor()
    qtbot.addWidget(editor)

    assert message.font().families() == list(CODE_FONT_FAMILIES)
    sheet = editor.styleSheet()
    assert all(f"'{family}'" in sheet for family in CODE_FONT_FAMILIES)
