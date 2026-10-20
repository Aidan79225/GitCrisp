"""A worktree operation that fails has to say so where the user can see it.

The operations log starts collapsed, and a line added to it while it is
collapsed is never read. Every other flow opens the log before reporting an
error; the worktree handlers did not, so a failed add, lock, unlock or remove
looked exactly like nothing having happened.
"""

from __future__ import annotations

import pytest

from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.presentation.main_window import MainWindow


class _Failing:
    def execute(self, *_args, **_kwargs):
        raise RuntimeError("refused by git")


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


def _log_is_open(window) -> bool:
    return not window._log_panel._body.isHidden()


def _log_text(window) -> str:
    return window._log_panel._body.toPlainText()


def _add(window) -> None:
    window._on_add_worktree_requested(
        {
            "location": "/tmp/wt",
            "branch": "feature",
            "create_new": True,
            "base_ref": "master",
            "switch_after": False,
        }
    )


@pytest.mark.parametrize(
    ("command", "run", "reported"),
    [
        ("add_worktree", _add, "Add worktree failed: refused by git"),
        (
            "lock_worktree",
            lambda w: w._run_lock_worktree_with_reason("/tmp/wt", ""),
            "Lock worktree failed: refused by git",
        ),
        (
            "unlock_worktree",
            lambda w: w._run_unlock_worktree("/tmp/wt"),
            "Unlock worktree failed: refused by git",
        ),
        (
            "remove_worktree",
            lambda w: w._run_remove_worktree("/tmp/wt", force=False),
            "Remove worktree failed: refused by git",
        ),
    ],
)
def test_a_failed_worktree_operation_opens_the_log(
    qtbot, window, monkeypatch, command, run, reported
):
    monkeypatch.setattr(window._commands, command, _Failing())
    assert not _log_is_open(window)

    run(window)

    qtbot.waitUntil(lambda: reported in _log_text(window), timeout=2000)
    assert _log_is_open(window)


def test_failing_to_list_worktrees_opens_the_log(window, monkeypatch):
    monkeypatch.setattr(window._queries, "list_worktrees", _Failing())

    window._open_worktrees_dialog()

    assert "Failed to list worktrees: refused by git" in _log_text(window)
    assert _log_is_open(window)
