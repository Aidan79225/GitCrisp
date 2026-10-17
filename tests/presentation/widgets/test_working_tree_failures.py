"""A failed stage, unstage, discard or ignore is reported, not swallowed.

Each of these runs from a Qt slot, so an exception escaping it reaches only
the crash log, and the user sees a click that did nothing.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from git_gui.domain.entities import FileDelta, FileStatus, StagingState
from git_gui.presentation.widgets.working_tree import WorkingTreeWidget

LOCKED = "the index is locked"


def _fs(path: str, status: StagingState) -> FileStatus:
    return FileStatus(path=path, status=status, delta=FileDelta.MODIFIED)


@pytest.fixture
def panel(qtbot):
    queries, commands = MagicMock(), MagicMock()
    queries.get_working_tree.execute.return_value = [
        _fs("a.txt", StagingState.UNSTAGED),
        _fs("b.txt", StagingState.STAGED),
    ]
    w = WorkingTreeWidget(queries, commands)
    qtbot.addWidget(w)
    w.reload = MagicMock()  # the refill is not under test here
    reported: list[str] = []
    w.commit_failed.connect(reported.append)
    return w, commands, reported


def test_a_failed_stage_all_is_reported(panel):
    w, commands, reported = panel
    commands.stage_files.execute.side_effect = RuntimeError(LOCKED)

    w._on_stage_all()

    assert reported == [f"Stage All failed: {LOCKED}"]


def test_a_failed_unstage_all_is_reported(panel):
    w, commands, reported = panel
    commands.unstage_files.execute.side_effect = RuntimeError(LOCKED)

    w._on_unstage_all()

    assert reported == [f"Unstage All failed: {LOCKED}"]


def test_a_failed_discard_is_reported_and_the_list_refreshed(panel, monkeypatch):
    """Discard can fail half-way, so the list must show what is left."""
    w, commands, reported = panel
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    commands.discard_file.execute.side_effect = PermissionError("report.xlsx is open")

    w._discard_file("report.xlsx")

    assert reported == ["Discard failed for report.xlsx: report.xlsx is open"]
    w.reload.assert_called_once()


def test_a_gitignore_that_is_not_utf8_is_reported(panel, tmp_path):
    w, _, reported = panel
    (tmp_path / ".gitignore").write_bytes("caf\xe9\n".encode("cp1252"))
    w.set_repo_path(str(tmp_path))

    w._ignore_file("foo.py")

    assert len(reported) == 1
    assert reported[0].startswith("Add to .gitignore failed: ")


def test_a_failed_checkbox_stage_is_reported(panel):
    w, commands, reported = panel
    commands.stage_files.execute.side_effect = RuntimeError(LOCKED)
    model = w._file_model
    model.reload([_fs("a.txt", StagingState.UNSTAGED)])

    model.setData(model.index(0), Qt.CheckState.Checked, Qt.CheckStateRole)

    assert reported == [f"Stage failed for a.txt: {LOCKED}"]


def test_a_failed_hunk_stage_in_the_diff_pane_is_reported(panel):
    w, commands, reported = panel
    commands.stage_hunk.execute.side_effect = RuntimeError(LOCKED)

    w._hunk_diff._on_hunk_toggled("a.txt", "@@ -1,2 +1,2 @@", True)

    assert reported == [f"Stage a.txt failed: {LOCKED}"]
