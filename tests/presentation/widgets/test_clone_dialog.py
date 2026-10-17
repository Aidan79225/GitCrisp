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


def test_cancel_is_disabled_while_a_clone_runs(qtbot, clone_gate):
    dialog = _dialog(qtbot)
    dialog._on_clone()
    assert not dialog._cancel_btn.isEnabled()
    clone_gate.set()
    qtbot.waitUntil(lambda: not dialog.isVisible())


def test_closing_the_dialog_mid_clone_is_ignored(qtbot, clone_gate):
    dialog = _dialog(qtbot)
    completed: list[str] = []
    dialog.clone_completed.connect(completed.append)
    dialog._on_clone()

    dialog.reject()

    assert dialog.isVisible()
    clone_gate.set()
    qtbot.waitUntil(lambda: bool(completed))


def _fail_clone(qtbot, error: Exception) -> CloneDialog:
    dialog = _dialog(qtbot)
    with patch(_CLONE_REPO, side_effect=error):
        dialog._on_clone()
        qtbot.waitUntil(lambda: dialog._error_label.isVisible())
    return dialog


def test_cancel_works_again_after_a_failed_clone(qtbot):
    dialog = _fail_clone(qtbot, RuntimeError("boom"))
    assert dialog._cancel_btn.isEnabled()
