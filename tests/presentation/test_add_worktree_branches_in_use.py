"""Add Worktree must not offer a branch git is certain to refuse.

Only linked worktrees counted as "in use", so the branch the main worktree
has checked out stayed selectable — and "Checkout in New Worktree…" on the
current branch preselected it with Add enabled, for git to fail with
"already checked out" after the dialog had closed.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.presentation.dialogs.add_worktree_dialog import AddWorktreeDialog
from git_gui.presentation.main_window import MainWindow


@pytest.fixture
def window(qtbot, repo_path, tmp_path):
    from main import _open_session

    queries, commands = _open_session(str(repo_path))
    w = MainWindow(
        queries,
        commands,
        JsonRepoStore(tmp_path / "repos.json"),
        JsonRemoteTagCache(),
        str(repo_path),
        session_factory=_open_session,
    )
    qtbot.addWidget(w)
    return w


@pytest.fixture
def shown(monkeypatch) -> list[AddWorktreeDialog]:
    dialogs: list[AddWorktreeDialog] = []

    def _record(self) -> int:
        dialogs.append(self)
        return 0

    monkeypatch.setattr(AddWorktreeDialog, "exec", _record)
    return dialogs


def test_the_main_worktrees_branch_cannot_be_picked(window, shown, repo_path):
    window._open_add_worktree_dialog(preselect_branch="master", default_create=False)

    (dialog,) = shown
    assert dialog.branch_disabled("master")
    assert not dialog.add_button_enabled()
    assert dialog.branch_tooltip("master") == f"Already checked out at {repo_path}"


def _fail(*_args, **_kwargs):
    raise OSError("index locked")


@pytest.mark.parametrize("query", ["list_worktrees", "get_branches"])
def test_a_branch_list_that_cannot_be_read_is_reported_not_offered(
    window, shown, monkeypatch, query
):
    """Opening anyway would offer the checked-out branch as free, or no branch."""
    monkeypatch.setattr(getattr(window._queries, query), "execute", _fail)
    window._log_panel = MagicMock()

    window._open_add_worktree_dialog(preselect_branch=None, default_create=False)

    assert shown == []
    window._log_panel.expand.assert_called_once_with()
    assert "index locked" in window._log_panel.log_error.call_args.args[0]
