"""Finding the open repo a linked worktree belongs to reads no other repo's path.

The lookup runs on the GUI thread at launch and on every switch into a
worktree, and it resolved each open repo listed before the owner. On Windows,
resolving a path on a share whose server is gone waits out the SMB timeout,
about 20 seconds: one open repo on an offline NAS froze the window that long
each time, and held a relaunch onto a worktree back from showing at all.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.presentation.main_window import MainWindow

_UNREACHABLE = r"\\192.0.2.1\share\proj"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _repo_with_worktree(tmp_path: Path) -> tuple[str, str]:
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
    return str(main), str(worktree.resolve())


@pytest.fixture
def resolved(monkeypatch) -> list[Path]:
    """Every path resolved; the unreachable one answers at once instead of
    waiting out a network timeout."""
    calls: list[Path] = []
    real_resolve = Path.resolve

    def _resolve(self: Path, strict: bool = False) -> Path:
        calls.append(Path(self))
        return self if str(self) == _UNREACHABLE else real_resolve(self, strict)

    monkeypatch.setattr(Path, "resolve", _resolve)
    return calls


def _window(qtbot, tmp_path: Path, open_repos: list[str], active: str) -> MainWindow:
    from main import _open_session

    store = JsonRepoStore(tmp_path / "repos.json")
    for path in reversed(open_repos):
        store.add_open(path)
    store.set_active(active)
    queries, commands = _open_session(active)
    win = MainWindow(
        queries, commands, store, JsonRemoteTagCache(), active, session_factory=_open_session
    )
    qtbot.addWidget(win)
    return win


def test_relaunching_onto_a_worktree_leaves_a_share_listed_above_alone(qtbot, tmp_path, resolved):
    main, worktree = _repo_with_worktree(tmp_path)

    win = _window(qtbot, tmp_path, [_UNREACHABLE, main], active=worktree)

    assert win._repo_list.worktree_owner() == main
    assert Path(_UNREACHABLE) not in resolved


def test_switching_into_a_worktree_leaves_a_share_listed_above_alone(qtbot, tmp_path, resolved):
    main, worktree = _repo_with_worktree(tmp_path)
    win = _window(qtbot, tmp_path, [_UNREACHABLE, main], active=main)

    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        win._switch_repo(worktree)

    assert win._repo_list.worktree_owner() == main
    assert Path(_UNREACHABLE) not in resolved


def test_the_owner_is_found_however_its_path_is_written(qtbot, tmp_path):
    """A stored path differs from git's only in separators and letter case."""
    main, worktree = _repo_with_worktree(tmp_path)
    spelled = Path(main).as_posix()
    if os.path.normcase("A") == "a":
        spelled = spelled.upper()

    win = _window(qtbot, tmp_path, [spelled], active=worktree)

    assert win._repo_list.worktree_owner() == spelled


def _directory_link(target: str, link: Path) -> None:
    try:
        if sys.platform == "win32":
            import _winapi

            _winapi.CreateJunction(target, str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this platform cannot link a directory")


def test_a_repo_opened_through_a_link_keeps_its_worktrees_on_a_switch(qtbot, tmp_path):
    """git names the main worktree by its real path, which the stored link
    spelling does not match; the switch in still knows where it came from."""
    main, worktree = _repo_with_worktree(tmp_path)
    link = tmp_path / "linked-main"
    _directory_link(main, link)
    win = _window(qtbot, tmp_path, [str(link)], active=str(link))

    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        win._switch_repo(worktree)

    assert win._repo_list.worktree_owner() == str(link)
