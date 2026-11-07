"""Add Worktree reads the typed location off the GUI thread.

The dialog checks the location on every change: whether it exists and, when it
is a folder, whether it is empty. On Windows the first touch of a share whose
server is gone waits out the SMB timeout, 42 seconds measured. The check ran
on the GUI thread, so the window froze with Not Responding in its title bar
and came back with Add enabled and no warning. The check now runs on a worker,
and Add waits for its answer so a location nobody has looked at is never
offered.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from git_gui.presentation.dialogs.add_worktree_dialog import AddWorktreeDialog
from git_gui.presentation.paths import same_path_text


@pytest.fixture
def disk_touches(monkeypatch) -> list[tuple[int, str]]:
    """(thread, path) of every stat, listing and scan, recorded as it happens."""
    touches: list[tuple[int, str]] = []

    def spy_on(name: str) -> None:
        real = getattr(os, name)

        def spy(path=".", *args, **kwargs):
            touches.append((threading.get_ident(), str(path)))
            return real(path, *args, **kwargs)

        monkeypatch.setattr(os, name, spy)

    for name in ("stat", "scandir", "listdir"):
        spy_on(name)
    return touches


def _reads_of(touches: list[tuple[int, str]], folder: Path, *, on_gui_thread: bool) -> list[str]:
    """The reads of *folder* itself made on the GUI thread, or off it."""
    gui_thread = threading.get_ident()
    return [
        path
        for thread, path in touches
        if (thread == gui_thread) is on_gui_thread and same_path_text(path, str(folder))
    ]


def _open_dialog(qtbot, tmp_path: Path, **kwargs) -> AddWorktreeDialog:
    dlg = AddWorktreeDialog(repo_path=str(tmp_path / "repo"), branches=["master"], **kwargs)
    qtbot.addWidget(dlg)
    return dlg


def _folder_with_a_file(parent: Path) -> Path:
    folder = parent / "taken"
    folder.mkdir()
    (folder / "notes.txt").write_text("x", encoding="utf-8")
    return folder


def _finish_all(held: list) -> None:
    """Run the checks the dialog handed over, oldest first."""
    queued = list(held)
    held.clear()
    for work in queued:
        work()


def test_a_typed_location_is_never_read_on_the_gui_thread(qtbot, tmp_path, disk_touches):
    folder = tmp_path / "wt"
    folder.mkdir()  # an empty folder is the longest check: stat it, then list it
    dlg = _open_dialog(qtbot, tmp_path)

    dlg.set_location(str(folder))

    assert _reads_of(disk_touches, folder, on_gui_thread=True) == []
    qtbot.waitUntil(dlg.add_button_enabled, timeout=5000)
    assert _reads_of(disk_touches, folder, on_gui_thread=True) == []
    assert _reads_of(disk_touches, folder, on_gui_thread=False) != []


def test_add_waits_for_the_check_of_each_new_location(qtbot, tmp_path):
    held: list = []
    dlg = _open_dialog(qtbot, tmp_path, run_in_background=held.append)
    dlg.set_location(str(tmp_path / "first"))
    _finish_all(held)
    assert dlg.add_button_enabled()

    dlg.set_location(str(tmp_path / "second"))

    assert not dlg.add_button_enabled()
    assert not dlg._location_error.isVisibleTo(dlg)
    _finish_all(held)
    assert dlg.add_button_enabled()
    assert not dlg._location_error.isVisibleTo(dlg)


def test_a_refusal_shows_only_once_the_check_has_answered(qtbot, tmp_path):
    held: list = []
    dlg = _open_dialog(qtbot, tmp_path, run_in_background=held.append)

    dlg.set_location(str(_folder_with_a_file(tmp_path)))

    assert not dlg._location_error.isVisibleTo(dlg)
    _finish_all(held)
    assert not dlg.add_button_enabled()
    assert "exists" in dlg._location_error.text()


def test_a_refusal_goes_as_soon_as_the_location_changes(qtbot, tmp_path):
    held: list = []
    dlg = _open_dialog(qtbot, tmp_path, run_in_background=held.append)
    dlg.set_location(str(_folder_with_a_file(tmp_path)))
    _finish_all(held)
    assert dlg._location_error.isVisibleTo(dlg)

    dlg.set_location(str(tmp_path / "wt"))

    assert not dlg._location_error.isVisibleTo(dlg)


def test_an_older_refusal_finishing_last_does_not_refuse_the_current_location(qtbot, tmp_path):
    held: list = []
    dlg = _open_dialog(qtbot, tmp_path, run_in_background=held.append)
    dlg.set_location(str(_folder_with_a_file(tmp_path)))
    dlg.set_location(str(tmp_path / "wt"))
    older, newer = held[-2:]

    newer()
    older()

    assert dlg.add_button_enabled()
    assert not dlg._location_error.isVisibleTo(dlg)


def test_an_older_all_clear_finishing_last_does_not_enable_add_for_a_refused_location(
    qtbot, tmp_path
):
    held: list = []
    dlg = _open_dialog(qtbot, tmp_path, run_in_background=held.append)
    dlg.set_location(str(tmp_path / "wt"))
    dlg.set_location(str(_folder_with_a_file(tmp_path)))
    older, newer = held[-2:]

    newer()
    older()

    assert not dlg.add_button_enabled()
    assert "exists" in dlg._location_error.text()


def test_a_relative_location_is_refused_at_once_without_a_disk_check(qtbot, tmp_path):
    held: list = []
    dlg = _open_dialog(qtbot, tmp_path, run_in_background=held.append)
    held.clear()

    dlg.set_location("wt")

    assert held == []
    assert not dlg.add_button_enabled()
    assert "absolute" in dlg._location_error.text()


def test_a_check_that_takes_a_while_says_so_until_it_answers(qtbot, tmp_path):
    held: list = []
    dlg = _open_dialog(qtbot, tmp_path, run_in_background=held.append)

    dlg.set_location(str(tmp_path / "wt"))

    assert not dlg._location_hint.isVisibleTo(dlg)  # a quick check never flashes it
    qtbot.waitUntil(lambda: dlg._location_hint.isVisibleTo(dlg), timeout=5000)
    _finish_all(held)
    assert not dlg._location_hint.isVisibleTo(dlg)


def test_a_check_that_answers_in_time_leaves_no_hint_waiting_to_appear(qtbot, tmp_path):
    held: list = []
    dlg = _open_dialog(qtbot, tmp_path, run_in_background=held.append)
    dlg.set_location(str(tmp_path / "wt"))

    _finish_all(held)

    assert not dlg._hint_timer.isActive()


@pytest.mark.parametrize("replacement", ["", "wt"])
def test_an_answer_for_a_location_since_replaced_without_a_disk_check_is_dropped(
    qtbot, tmp_path, replacement
):
    held: list = []
    dlg = _open_dialog(qtbot, tmp_path, run_in_background=held.append)
    dlg.set_location(str(_folder_with_a_file(tmp_path)))
    stale = held[-1]
    dlg.set_location(replacement)
    before = (dlg._location_error.isVisibleTo(dlg), dlg._location_error.text())

    stale()

    assert (dlg._location_error.isVisibleTo(dlg), dlg._location_error.text()) == before
