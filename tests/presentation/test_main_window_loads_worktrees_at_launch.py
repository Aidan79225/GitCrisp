"""A window opened straight onto a repo has to know its worktrees.

They were loaded only by the repo-switch handler, so the ordinary launch —
which builds the window on the last repo without switching — showed no
worktree rows in the repo list and no '+' badges in the sidebar, and the
Branches dialog had no worktree paths, until the user switched repos and back.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.presentation.main_window import MainWindow


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def repo_with_worktree(tmp_path) -> tuple[Path, Path]:
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "master", ".")
    _git(main, "config", "user.name", "T")
    _git(main, "config", "user.email", "t@e.com")
    (main / "a.txt").write_text("x\n")
    _git(main, "add", "a.txt")
    _git(main, "commit", "-qm", "init")
    linked = tmp_path / "linked"
    _git(main, "worktree", "add", "-q", "-b", "feat", str(linked))
    return main, linked


def test_launching_on_a_repo_loads_its_worktrees(qtbot, tmp_path, repo_with_worktree):
    from main import _open_session

    main, linked = repo_with_worktree
    store = JsonRepoStore(tmp_path / "repos.json")
    store.add_open(str(main))
    queries, commands = _open_session(str(main))

    win = MainWindow(
        queries,
        commands,
        store,
        JsonRemoteTagCache(),
        str(main),
        session_factory=_open_session,
    )
    qtbot.addWidget(win)

    assert win._sidebar.has_worktree_badge("feat")
    assert Path(win._worktree_paths_by_branch["feat"]) == linked
