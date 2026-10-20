"""The open Worktrees dialog shows what its own Lock, Remove and Add did.

Its actions run on background threads after the dialog has emitted them, and
nothing gave the dialog the list again, so its table went on showing the
worktrees as they were when it opened.
"""

from __future__ import annotations

from unittest.mock import patch

from PySide6.QtWidgets import QMessageBox

from git_gui.domain.entities import Worktree
from git_gui.presentation.dialogs.worktrees_dialog import WorktreesDialog
from git_gui.presentation.main_window import MainWindow
from tests.presentation.window_helpers import empty_repo_store, wired_window

_MAIN = "/repo"
_LINKED = "/repo-wt"


def _worktree(path: str, *, is_main: bool = False, lock_reason: str | None = None) -> Worktree:
    return Worktree(
        path=path,
        branch="master" if is_main else "feature",
        head_sha="a" * 40,
        is_locked=lock_reason is not None,
        lock_reason=lock_reason,
        is_bare=False,
        is_main=is_main,
    )


class _Worktrees:
    """A worktree list that the fake lock and remove commands change."""

    def __init__(self) -> None:
        self.items = [_worktree(_MAIN, is_main=True), _worktree(_LINKED)]

    def lock(self, path: str, reason: str | None = None) -> None:
        self.items = [_worktree(_MAIN, is_main=True), _worktree(path, lock_reason=reason)]

    def remove(self, path: str, force: bool = False) -> None:
        self.items = [wt for wt in self.items if wt.path != path]

    def add(self, path: str, branch: str, **_kwargs) -> Worktree:
        added = _worktree(path)
        self.items = [*self.items, added]
        return added


def _make_window(qtbot, worktrees: _Worktrees) -> MainWindow:
    repo_store = empty_repo_store()
    repo_store.get_open_repos.return_value = [_MAIN]
    repo_store.get_active.return_value = _MAIN
    win = wired_window(qtbot, repo_store)
    win._repo_path = _MAIN
    win._queries.list_worktrees.execute.side_effect = lambda: list(worktrees.items)
    win._commands.lock_worktree.execute.side_effect = worktrees.lock
    win._commands.remove_worktree.execute.side_effect = worktrees.remove
    win._commands.add_worktree.execute.side_effect = worktrees.add
    return win


def _run_dialog(win: MainWindow, act) -> list[WorktreesDialog]:
    """Open the Worktrees dialog and run *act* on it while it is up."""
    shown: list[WorktreesDialog] = []

    def _exec(dialog: WorktreesDialog) -> int:
        shown.append(dialog)
        act(dialog)
        return 0

    with patch.object(WorktreesDialog, "exec", _exec):
        win._open_worktrees_dialog()
    return shown


def _paths(dialog: WorktreesDialog) -> list[str]:
    return [dialog.row_path(row) for row in range(dialog.row_count())]


def test_locking_from_the_dialog_shows_the_lock_in_it(qtbot):
    win = _make_window(qtbot, _Worktrees())

    def _lock(dialog: WorktreesDialog) -> None:
        dialog.lock_requested.emit(_LINKED, "on a USB drive")
        qtbot.waitUntil(lambda: dialog.row_locked_text(1) == "on a USB drive", timeout=2000)

    assert _run_dialog(win, _lock)


def test_removing_from_the_dialog_takes_the_row_out_of_it(qtbot):
    win = _make_window(qtbot, _Worktrees())

    def _remove(dialog: WorktreesDialog) -> None:
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            dialog.remove_requested.emit(_LINKED)
        qtbot.waitUntil(lambda: _paths(dialog) == [_MAIN], timeout=2000)

    assert _run_dialog(win, _remove)


def test_adding_while_the_dialog_is_open_lists_the_new_worktree(qtbot):
    win = _make_window(qtbot, _Worktrees())
    added = "/repo-wt2"

    def _add(dialog: WorktreesDialog) -> None:
        win._on_add_worktree_requested(
            {
                "location": added,
                "branch": "feature",
                "create_new": False,
                "base_ref": None,
                "switch_after": False,
            }
        )
        qtbot.waitUntil(lambda: added in _paths(dialog), timeout=2000)

    assert _run_dialog(win, _add)


def test_the_dialog_is_forgotten_once_closed(qtbot):
    win = _make_window(qtbot, _Worktrees())
    shown = _run_dialog(win, lambda _dialog: None)

    win._load_worktrees_for_active_repo()

    assert win._worktrees_dialog is None
    assert _paths(shown[0]) == [_MAIN, _LINKED]
