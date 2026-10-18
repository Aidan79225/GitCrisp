"""Which files Stage All and Unstage All move across the index.

A partly staged file sits on both sides of the index, so both buttons take it.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from git_gui.domain.entities import FileDelta, FileStatus, StagingState
from git_gui.presentation.widgets.working_tree import WorkingTreeWidget


def _fs(path: str, status: StagingState) -> FileStatus:
    return FileStatus(path=path, status=status, delta=FileDelta.MODIFIED)


@pytest.fixture
def panel(qtbot):
    queries, commands = MagicMock(), MagicMock()
    queries.get_working_tree.execute.return_value = [
        _fs("unstaged.txt", StagingState.UNSTAGED),
        _fs("staged.txt", StagingState.STAGED),
        _fs("partly.txt", StagingState.STAGED),
        _fs("partly.txt", StagingState.UNSTAGED),
    ]
    w = WorkingTreeWidget(queries, commands)
    qtbot.addWidget(w)
    w.reload = MagicMock()  # the refill is not under test here
    return w, commands


def test_stage_all_stages_every_file_with_unstaged_changes(panel):
    w, commands = panel

    w._on_stage_all()

    (paths,), _ = commands.stage_files.execute.call_args
    assert sorted(paths) == ["partly.txt", "unstaged.txt"]
    commands.unstage_files.execute.assert_not_called()


def test_unstage_all_unstages_every_file_with_staged_changes(panel):
    w, commands = panel

    w._on_unstage_all()

    (paths,), _ = commands.unstage_files.execute.call_args
    assert sorted(paths) == ["partly.txt", "staged.txt"]
    commands.stage_files.execute.assert_not_called()


def test_nothing_to_stage_runs_no_command(panel):
    w, commands = panel
    w._queries.get_working_tree.execute.return_value = [_fs("staged.txt", StagingState.STAGED)]

    w._on_stage_all()

    commands.stage_files.execute.assert_not_called()
    w.reload.assert_not_called()
