"""Locking and unlocking a worktree must refresh the list, not log a failure.

Both workers used to report success on `succeeded = Signal(str)` — the signal
that carries the removed path — with no argument. Qt raised
"succeeded(QString) needs 1 argument(s), 0 given!" inside the worker's own
try block, so the op that had already succeeded surfaced as
"Unlock worktree failed: ..." and the list never refreshed.
"""

from __future__ import annotations

import pytest

from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.presentation.main_window import MainWindow


class _FakeCommand:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def execute(self, *args, **kwargs) -> None:
        self.calls.append((args, kwargs))


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
def refreshes(window, monkeypatch):
    seen: list[bool] = []
    monkeypatch.setattr(window, "_load_worktrees_for_active_repo", lambda: seen.append(True))
    return seen


@pytest.fixture
def errors(window, monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(window._log_panel, "log_error", seen.append)
    return seen


def test_unlock_refreshes_the_worktree_list(qtbot, window, refreshes, errors, monkeypatch):
    unlock = _FakeCommand()
    monkeypatch.setattr(window._commands, "unlock_worktree", unlock)

    window._run_unlock_worktree("/tmp/wt")

    qtbot.waitUntil(lambda: bool(refreshes), timeout=2000)
    assert unlock.calls == [(("/tmp/wt",), {})]
    assert errors == []


def test_lock_refreshes_the_worktree_list(qtbot, window, refreshes, errors, monkeypatch):
    lock = _FakeCommand()
    monkeypatch.setattr(window._commands, "lock_worktree", lock)

    window._run_lock_worktree_with_reason("/tmp/wt", "busy")

    qtbot.waitUntil(lambda: bool(refreshes), timeout=2000)
    assert lock.calls == [(("/tmp/wt",), {"reason": "busy"})]
    assert errors == []


def test_a_real_unlock_failure_still_reaches_the_log(qtbot, window, refreshes, errors, monkeypatch):
    class _Boom:
        def execute(self, *_a, **_k):
            raise RuntimeError("worktree is not locked")

    monkeypatch.setattr(window._commands, "unlock_worktree", _Boom())

    window._run_unlock_worktree("/tmp/wt")

    qtbot.waitUntil(lambda: bool(errors), timeout=2000)
    assert errors == ["Unlock worktree failed: worktree is not locked"]
    assert refreshes == []
