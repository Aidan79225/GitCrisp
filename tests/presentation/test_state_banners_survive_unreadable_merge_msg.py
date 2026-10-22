"""A merge whose message cannot be read is still shown as a merge.

The state and the message were read in one try, so failing to read MERGE_MSG
showed the repo as clean: the merge banner and its Abort button went, and
Amend came back, while the merge was still in progress. Nothing was logged.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

from git_gui.domain.entities import RepoState, RepoStateInfo
from git_gui.presentation.main_window import MainWindow
from tests.presentation.window_helpers import blank_window


def _make_window(qtbot) -> MainWindow:
    win = blank_window(qtbot)
    win._queries = MagicMock()
    win._working_tree = MagicMock()
    win._diff = MagicMock()
    return win


def _state_given_to(banner: MagicMock) -> object:
    """The state one banner update was given: the member itself, not its name."""
    banner.assert_called_once()
    return banner.call_args.args[0]


def _merging_with_unreadable_message(win: MainWindow) -> None:
    win._queries.get_repo_state.execute.return_value = RepoStateInfo(RepoState.MERGING, "master")
    win._queries.get_merge_msg.execute.side_effect = UnicodeDecodeError(
        "utf-8", b"\xff", 0, 1, "invalid start byte"
    )


def test_an_unreadable_merge_message_keeps_the_merge_banner(qtbot):
    win = _make_window(qtbot)
    _merging_with_unreadable_message(win)

    win._refresh_state_banners()

    win._working_tree.update_conflict_banner.assert_called_once_with(RepoState.MERGING, None)
    assert _state_given_to(win._working_tree.update_conflict_banner) is RepoState.MERGING
    assert _state_given_to(win._diff.update_state_banner) is RepoState.MERGING


def test_an_unreadable_merge_message_is_logged(qtbot, caplog):
    win = _make_window(qtbot)
    _merging_with_unreadable_message(win)

    with caplog.at_level(logging.WARNING):
        win._refresh_state_banners()

    assert "invalid start byte" in caplog.text


def test_an_unreadable_repo_state_is_logged_and_shown_as_clean(qtbot, caplog):
    win = _make_window(qtbot)
    win._queries.get_repo_state.execute.side_effect = OSError("HEAD is gone")

    with caplog.at_level(logging.WARNING):
        win._refresh_state_banners()

    assert "HEAD is gone" in caplog.text
    win._working_tree.update_conflict_banner.assert_called_once_with(RepoState.CLEAN, None)
    assert _state_given_to(win._working_tree.update_conflict_banner) is RepoState.CLEAN
    assert _state_given_to(win._diff.update_state_banner) is RepoState.CLEAN
