"""Behaviour tests for CloneDialog: folder-name detection, the running clone, and its errors."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from git_gui.infrastructure.git_clone import CloneCancelled
from git_gui.presentation.paths import same_path_text
from git_gui.presentation.widgets.clone_dialog import (
    CloneDialog,
    _input_problem,
    _parse_repo_name,
)

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
    with patch(_CLONE_REPO, side_effect=lambda url, dest, **_: gate.wait(5)):
        yield gate
        gate.set()


def test_cancel_stays_available_while_a_clone_runs(qtbot, clone_gate):
    dialog = _dialog(qtbot)
    dialog._on_clone()
    assert dialog._cancel_btn.isEnabled()


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Space], ids=["enter", "space"])
def test_a_key_pressed_again_after_starting_a_clone_does_not_cancel_it(qtbot, clone_gate, key):
    """Starting a clone disables every control but Cancel, so the focus moved
    on to Cancel, and a second Enter or a Space stopped and deleted the clone."""
    dialog = _dialog(qtbot)
    dialog._url_edit.setFocus()
    QTest.keyClick(dialog._url_edit, Qt.Key.Key_Return)
    assert dialog._cloning

    QTest.keyClick(dialog.focusWidget() or dialog, key)

    assert dialog.isVisible()
    assert not dialog._cancel_requested.is_set()


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


def test_cancel_takes_the_keyboard_focus_again_after_a_failed_clone(qtbot):
    dialog = _fail_clone(qtbot, RuntimeError("boom"))
    assert dialog._cancel_btn.focusPolicy() == Qt.FocusPolicy.StrongFocus


def test_a_failed_clone_shows_gits_reason(qtbot):
    reason = "fatal: destination path 'repo' already exists and is not an empty directory."
    dialog = _fail_clone(qtbot, RuntimeError(reason))
    assert dialog._error_label.text() == reason


def test_a_failure_without_gits_output_shows_the_error_itself(qtbot):
    dialog = _fail_clone(qtbot, OSError("git executable not found"))
    assert dialog._error_label.text() == "git executable not found"


@pytest.fixture
def clone_until_cancelled():
    """Make clone_repo run until it is cancelled; yields whether it saw the cancel."""
    seen: list[bool] = []

    def clone(url, dest, on_progress=None, cancelled=None):
        seen.append(cancelled is not None and cancelled.wait(5))
        raise CloneCancelled("cancelled")

    with patch(_CLONE_REPO, side_effect=clone):
        yield seen


@pytest.mark.parametrize(
    "dismiss",
    [
        pytest.param(lambda d: d._cancel_btn.click(), id="cancel"),
        pytest.param(lambda d: QTest.keyClick(d, Qt.Key.Key_Escape), id="escape"),
        pytest.param(lambda d: d.close(), id="close"),
    ],
)
def test_dismissing_the_dialog_mid_clone_stops_the_clone(qtbot, clone_until_cancelled, dismiss):
    dialog = _dialog(qtbot)
    dialog._on_clone()

    dismiss(dialog)

    qtbot.waitUntil(lambda: bool(clone_until_cancelled))
    assert clone_until_cancelled == [True]


def test_a_cancelled_clone_is_not_reported_as_a_failure(qtbot, clone_until_cancelled):
    dialog = _dialog(qtbot)
    dialog._on_clone()

    dialog.reject()
    qtbot.waitUntil(lambda: bool(clone_until_cancelled))
    qtbot.wait(200)

    assert dialog._error_label.text() == ""


_IN_USE = "[WinError 32] The process cannot access the file: 'repo\\.git\\config'"


@pytest.fixture
def clone_that_cannot_clean_up():
    """Make clone_repo run until it is cancelled, then fail to remove what it wrote."""

    def clone(url, dest, on_progress=None, cancelled=None):
        cancelled.wait(5)
        raise CloneCancelled("cancelled", cleanup_error=PermissionError(_IN_USE))

    with patch(_CLONE_REPO, side_effect=clone):
        yield


def test_a_cancelled_clone_that_left_files_behind_says_where_and_why(
    qtbot, clone_that_cannot_clean_up
):
    """The dialog has closed by then, so it hands the report on rather than showing it."""
    dialog = _dialog(qtbot)
    dialog._on_clone()

    with qtbot.waitSignal(dialog.cleanup_failed) as report:
        dialog.reject()

    assert report.args == [str(Path(dialog._folder_edit.text()) / "repo"), _IN_USE]


# --- Input: what has to be filled in before a clone starts ----------------------------------


@pytest.mark.parametrize(
    ("url", "folder", "name", "problem"),
    [
        pytest.param("", "", "", "URL is required.", id="nothing-filled-in-asks-for-the-url"),
        pytest.param("", "/x", "repo", "URL is required.", id="no-url"),
        pytest.param("u", "", "repo", "Location is required.", id="no-location"),
        pytest.param("u", "/x", "", "Folder name is required.", id="no-folder-name"),
        pytest.param("u", "/x", "repo", None, id="nothing-missing"),
    ],
)
def test_a_clone_asks_for_the_first_field_that_is_missing(url, folder, name, problem):
    assert _input_problem(url, folder, name) == problem


# --- Folder name: the clone stays inside Location -------------------------------------------

_OUTSIDE_THE_LOCATION = "Folder name must stay inside the location."
_WINDOWS_ONLY = pytest.mark.skipif(
    os.name != "nt", reason="drives, UNC shares and backslash separators exist only on Windows"
)


@pytest.fixture
def location(tmp_path) -> Path:
    return tmp_path / "location"


def _press_clone(qtbot, location: Path, name: str):
    """Type `name` under `location`, press Clone; return the dialog and the stand-in for git."""
    dialog = _dialog(qtbot)
    dialog._folder_edit.setText(str(location))
    dialog._name_edit.setText(name)
    with patch(_CLONE_REPO) as clone:
        dialog._on_clone()
    return dialog, clone


def _assert_refused(dialog: CloneDialog, clone) -> None:
    assert not dialog._cloning, "a clone was started"
    assert dialog._error_label.isVisible()
    assert dialog._error_label.text() == _OUTSIDE_THE_LOCATION
    clone.assert_not_called()


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("../x", id="beside-the-location"),
        pytest.param("a/../../x", id="up-out-of-a-subfolder"),
        pytest.param("..", id="the-parent-folder-itself"),
        pytest.param(r"..\x", id="beside-the-location-with-backslash", marks=_WINDOWS_ONLY),
        pytest.param(r"D:\x", id="another-drive", marks=_WINDOWS_ONLY),
        pytest.param("D:x", id="another-drive-without-a-root", marks=_WINDOWS_ONLY),
        pytest.param(r"\x", id="the-root-of-the-drive", marks=_WINDOWS_ONLY),
        pytest.param(r"\\server\share\x", id="a-network-share", marks=_WINDOWS_ONLY),
    ],
)
def test_a_folder_name_that_leaves_the_location_starts_no_clone(qtbot, location, name):
    """Git was given Location joined with whatever was typed, so a name that climbed out
    of it or named another drive cloned there, with no sign of it in the dialog."""
    _assert_refused(*_press_clone(qtbot, location, name))


def test_an_absolute_folder_name_outside_the_location_starts_no_clone(qtbot, location, tmp_path):
    _assert_refused(*_press_clone(qtbot, location, str(tmp_path / "elsewhere")))


def test_a_url_ending_in_dot_dot_cannot_clone_into_the_parent_of_the_location(qtbot, location):
    """Pasting a URL fills in its last part as the folder name, and for this one that is '..'."""
    dialog = _dialog(qtbot)
    dialog._folder_edit.setText(str(location))
    dialog._url_edit.setText("https://example.com/user/..")
    assert dialog._name_edit.text() == ".."

    with patch(_CLONE_REPO) as clone:
        dialog._on_clone()

    _assert_refused(dialog, clone)


def test_a_folder_name_cannot_leave_a_relative_location(qtbot, tmp_path, monkeypatch):
    """A relative Location is the working folder, and its parent is outside it."""
    monkeypatch.chdir(tmp_path)

    _assert_refused(*_press_clone(qtbot, Path("."), "../x"))


@pytest.mark.parametrize(
    ("name", "folders_inside"),
    [
        pytest.param("group/repo", ("group", "repo"), id="a-subfolder"),
        pytest.param(".", (), id="the-location-itself"),
    ],
)
def test_a_folder_name_that_stays_inside_the_location_clones_there(
    qtbot, location, name, folders_inside
):
    dialog = _dialog(qtbot)
    dialog._folder_edit.setText(str(location))
    dialog._name_edit.setText(name)

    with patch(_CLONE_REPO) as clone, qtbot.waitSignal(dialog.clone_completed):
        dialog._on_clone()

    assert same_path_text(clone.call_args.args[1], str(location.joinpath(*folders_inside)))
