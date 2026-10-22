"""Force remove on a locked worktree removes it, once the user has agreed.

Passing --force once leaves a lock in force; the lock is lifted only by
asking for that. Force remove used to ask for --force alone, so git refused
again and the "is locked" prompt came back after every click, for as long as
the user kept agreeing. Deleting a branch held by a locked worktree failed
the same way, with git's "cannot remove a locked working tree" in the log.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.presentation.main_window import MainWindow

_LOCKED = "Worktree is locked"
_DIRTY = "Worktree is dirty"
_BRANCH_FORCE = "Force remove worktree?"


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)
    return done.stdout.decode()


def _repo_with_locked_worktree(tmp_path: Path) -> tuple[str, str]:
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "master", ".")
    _git(main, "config", "user.name", "T")
    _git(main, "config", "user.email", "t@e.com")
    (main / "a.txt").write_text("x\n")
    _git(main, "add", "a.txt")
    _git(main, "commit", "-qm", "init")
    worktree = tmp_path / "feature-wt"
    _git(main, "worktree", "add", "-q", "-b", "feature", str(worktree))
    _git(main, "worktree", "lock", "--reason", "on a USB stick", str(worktree))
    return str(main), str(worktree.resolve())


def _is_locked(main: str, worktree: str) -> bool:
    listing = _git(Path(main), "worktree", "list", "--porcelain").split("\n\n")
    entry = next(e for e in listing if Path(e.splitlines()[0].split(" ", 1)[1]) == Path(worktree))
    return any(line.startswith("locked") for line in entry.splitlines())


@pytest.fixture
def repo(tmp_path) -> tuple[str, str]:
    return _repo_with_locked_worktree(tmp_path)


@pytest.fixture
def window(qtbot, tmp_path, repo) -> MainWindow:
    from main import _open_session

    main, _ = repo
    store = JsonRepoStore(tmp_path / "repos.json")
    store.add_open(main)
    queries, commands = _open_session(main)
    win = MainWindow(
        queries, commands, store, JsonRemoteTagCache(), main, session_factory=_open_session
    )
    qtbot.addWidget(win)
    return win


class _Prompts:
    """Answers each force prompt by its title, the first time it is asked.

    Asked again, it is cancelled, so a prompt that keeps coming back shows up
    as a second entry in `asked` rather than as a test that never ends.
    """

    def __init__(self, monkeypatch, *, agree_to: set[str]) -> None:
        self.asked: list[str] = []
        self._agree_to = agree_to
        monkeypatch.setattr(QMessageBox, "exec", lambda box: self._answer(box))

    def _answer(self, box: QMessageBox) -> int:
        title = box.windowTitle()
        agree = title in self._agree_to and title not in self.asked
        self.asked.append(title)
        role = QMessageBox.DestructiveRole if agree else QMessageBox.RejectRole
        next(b for b in box.buttons() if box.buttonRole(b) == role).click()
        return 0


def test_force_removing_a_locked_worktree_removes_it(qtbot, window, repo, monkeypatch):
    _, worktree = repo
    prompts = _Prompts(monkeypatch, agree_to={_LOCKED})

    window._run_remove_worktree(worktree, force=False)

    qtbot.waitUntil(lambda: not Path(worktree).exists(), timeout=10000)
    assert prompts.asked == [_LOCKED]


def test_a_locked_worktree_with_changes_is_asked_about_both(qtbot, window, repo, monkeypatch):
    _, worktree = repo
    (Path(worktree) / "a.txt").write_text("edited\n")
    prompts = _Prompts(monkeypatch, agree_to={_LOCKED, _DIRTY})

    window._run_remove_worktree(worktree, force=False)

    qtbot.waitUntil(lambda: not Path(worktree).exists(), timeout=10000)
    assert prompts.asked == [_LOCKED, _DIRTY]


def test_declining_to_discard_changes_keeps_the_worktree_and_its_lock(
    qtbot, window, repo, monkeypatch
):
    main, worktree = repo
    (Path(worktree) / "a.txt").write_text("edited\n")
    prompts = _Prompts(monkeypatch, agree_to={_LOCKED})

    window._run_remove_worktree(worktree, force=False)

    qtbot.waitUntil(lambda: _DIRTY in prompts.asked, timeout=10000)
    qtbot.wait(300)
    assert prompts.asked == [_LOCKED, _DIRTY]
    assert (Path(worktree) / "a.txt").read_text() == "edited\n"
    assert _is_locked(main, worktree)


def test_deleting_a_branch_held_by_a_locked_worktree_removes_both(qtbot, window, repo, monkeypatch):
    main, worktree = repo
    prompts = _Prompts(monkeypatch, agree_to={_BRANCH_FORCE})
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.Yes)

    window._on_delete_branch("feature")

    assert prompts.asked == [_BRANCH_FORCE]
    assert not Path(worktree).exists()
    assert "feature" not in _git(Path(main), "branch", "--list", "feature")


def test_deleting_a_branch_held_by_a_locked_dirty_worktree_asks_about_both(
    qtbot, window, repo, monkeypatch
):
    main, worktree = repo
    (Path(worktree) / "a.txt").write_text("edited\n")
    asked: list[str] = []
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.Yes)
    monkeypatch.setattr(
        window, "_ask_force_remove_worktree", lambda _path, detail: asked.append(detail) or True
    )

    window._on_delete_branch("feature")

    assert asked == ["is locked", "has uncommitted changes"]
    assert not Path(worktree).exists()
    assert "feature" not in _git(Path(main), "branch", "--list", "feature")
