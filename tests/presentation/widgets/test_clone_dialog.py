"""Behaviour tests for CloneDialog: folder-name detection, the running clone, and its errors."""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from git_gui.presentation.widgets.clone_dialog import CloneDialog, _parse_repo_name

_CLONE_REPO = "git_gui.presentation.widgets.clone_dialog.clone_repo"


@pytest.mark.parametrize(
    ("url", "name"),
    [
        (r"D:\repos\foo", "foo"),
        (r"C:\src\proj.git", "proj"),
        ("C:\\src\\proj\\", "proj"),
        ("D:/repos/foo", "foo"),
        ("https://github.com/user/repo.git", "repo"),
        ("git@github.com:user/repo.git", "repo"),
    ],
)
def test_folder_name_is_the_last_part_of_the_source(url, name):
    assert _parse_repo_name(url) == name


def _dialog(qtbot) -> CloneDialog:
    dialog = CloneDialog()
    qtbot.addWidget(dialog)
    dialog._url_edit.setText("https://example.com/user/repo.git")
    dialog.show()
    return dialog


@pytest.fixture
def clone_gate():
    """Make clone_repo wait until the test sets the returned event."""
    gate = threading.Event()
    with patch(_CLONE_REPO, side_effect=lambda url, dest, on_progress=None: gate.wait(5)):
        yield gate
        gate.set()


def test_cancel_stays_available_while_a_clone_runs(qtbot, clone_gate):
    dialog = _dialog(qtbot)
    dialog._on_clone()
    assert dialog._cancel_btn.isEnabled()


def test_cancelling_mid_clone_closes_the_dialog(qtbot, clone_gate):
    dialog = _dialog(qtbot)
    dialog._on_clone()

    dialog._cancel_btn.click()

    assert not dialog.isVisible()


def test_a_clone_cancelled_midway_is_not_opened_when_git_finishes(qtbot, clone_gate):
    dialog = _dialog(qtbot)
    completed: list[str] = []
    dialog.clone_completed.connect(completed.append)
    dialog._on_clone()
    reported: list[str] = []
    dialog._clone_signals.finished.connect(reported.append)

    dialog.reject()
    clone_gate.set()
    qtbot.waitUntil(lambda: bool(reported))

    assert completed == []


def _fail_clone(qtbot, error: Exception) -> CloneDialog:
    dialog = _dialog(qtbot)
    with patch(_CLONE_REPO, side_effect=error):
        dialog._on_clone()
        qtbot.waitUntil(lambda: dialog._error_label.isVisible())
    return dialog


def test_cancel_works_again_after_a_failed_clone(qtbot):
    dialog = _fail_clone(qtbot, RuntimeError("boom"))
    assert dialog._cancel_btn.isEnabled()


def test_a_failed_clone_shows_gits_reason(qtbot):
    reason = "fatal: destination path 'repo' already exists and is not an empty directory."
    dialog = _fail_clone(qtbot, RuntimeError(reason))
    assert dialog._error_label.text() == reason


def test_a_failure_without_gits_output_shows_the_error_itself(qtbot):
    dialog = _fail_clone(qtbot, OSError("git executable not found"))
    assert dialog._error_label.text() == "git executable not found"
