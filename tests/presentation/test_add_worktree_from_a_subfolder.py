"""Add Worktree knows which worktree is open when a repo was opened from a subfolder.

Open Repository accepts any folder inside a repository, and the window keeps
the folder it was given. Add Worktree compared that folder with where each
branch is checked out, so the branch of the very worktree on screen read as
"Already checked out at <repo>" with a switch to it, and switching rebuilt
the session and listed the repository twice. The default location for a new
worktree was made from the subfolder too, inside the worktree itself.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.presentation.dialogs.add_worktree_dialog import AddWorktreeDialog
from git_gui.presentation.main_window import MainWindow


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path) -> Path:
    """A repo on master with a src/ folder, and a feature branch checked out
    in a linked worktree nested inside it."""
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "master", ".")
    _git(repo, "config", "user.name", "T")
    _git(repo, "config", "user.email", "t@e.com")
    (repo / "src" / "a.txt").write_text("x\n")
    _git(repo, "add", "src/a.txt")
    _git(repo, "commit", "-qm", "init")
    _git(repo, "worktree", "add", "-q", "-b", "feature", str(repo / ".worktrees" / "feature"))
    return repo


@pytest.fixture
def shown(monkeypatch) -> list[AddWorktreeDialog]:
    dialogs: list[AddWorktreeDialog] = []
    monkeypatch.setattr(AddWorktreeDialog, "exec", lambda dialog: dialogs.append(dialog) or 0)
    return dialogs


def _window_on(qtbot, tmp_path: Path, path: Path) -> MainWindow:
    from main import _open_session

    queries, commands = _open_session(str(path))
    win = MainWindow(
        queries,
        commands,
        JsonRepoStore(tmp_path / "repos.json"),
        JsonRemoteTagCache(),
        str(path),
        session_factory=_open_session,
    )
    qtbot.addWidget(win)
    return win


def _add_worktree_for(win: MainWindow, shown, branch: str) -> AddWorktreeDialog:
    win._open_add_worktree_dialog(preselect_branch=branch, default_create=False)
    (dialog,) = shown
    return dialog


def test_the_open_worktrees_branch_offers_no_switch_from_a_subfolder(qtbot, tmp_path, repo, shown):
    win = _window_on(qtbot, tmp_path, repo / "src")

    dialog = _add_worktree_for(win, shown, "master")

    assert not dialog._switch_btn.isVisibleTo(dialog)
    assert "this worktree" in dialog._in_use_label.text()


def test_a_new_worktree_goes_beside_the_repo_not_inside_it(qtbot, tmp_path, repo, shown):
    win = _window_on(qtbot, tmp_path, repo / "src")

    dialog = _add_worktree_for(win, shown, "master")

    assert Path(dialog.location()) == tmp_path / "repo-master"


def test_a_worktree_nested_in_the_main_one_still_offers_the_main_ones_branch(
    qtbot, tmp_path, repo, shown
):
    """From the nested worktree, master is checked out somewhere else."""
    win = _window_on(qtbot, tmp_path, repo / ".worktrees" / "feature")

    dialog = _add_worktree_for(win, shown, "master")

    assert dialog._switch_btn.isVisibleTo(dialog)
    assert dialog._in_use_label.text() == f"Already checked out at {repo}"
