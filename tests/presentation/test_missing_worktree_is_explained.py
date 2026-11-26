"""A worktree with no checkout on this machine cannot be opened from here, and
the window says why instead of failing on a thread.

Such a worktree is registered in the admin dir — added from another machine
or a container, or its folder deleted — so git still lists it and the branch
it holds is still in use. Opening it used to run into pygit2's "Repository not
found", which names the path and nothing else; checking out its branch here
used to switch to it, and fail the same way.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from git_gui.domain.entities import Branch
from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.presentation.main_window import MainWindow


@pytest.fixture
def missing_worktree(repo_path, tmp_path_factory) -> str:
    """A linked worktree of repo_path on branch feat whose folder is gone."""
    wt_path = tmp_path_factory.mktemp("wt") / "feat"
    subprocess.run(
        ["git", "-C", str(repo_path), "worktree", "add", "-b", "feat", str(wt_path)],
        check=True,
        capture_output=True,
    )
    shutil.rmtree(wt_path)
    return str(wt_path.resolve())


@pytest.fixture
def window(qtbot, repo_path, missing_worktree, tmp_path_factory):
    """The window on repo_path, with its worktrees loaded — the missing one among them."""
    from main import _open_session

    opened: list[str] = []

    def _session_factory(path: str):
        opened.append(path)
        return _open_session(path)

    queries, commands = _open_session(str(repo_path))
    w = MainWindow(
        queries,
        commands,
        JsonRepoStore(tmp_path_factory.mktemp("store") / "repos.json"),
        JsonRemoteTagCache(),
        str(repo_path),
        session_factory=_session_factory,
    )
    w.opened_by_factory = opened
    qtbot.addWidget(w)
    w._load_worktrees_for_active_repo()
    return w


def _log_is_open(window) -> bool:
    return not window._log_panel._body.isHidden()


def _log_text(window) -> str:
    return window._log_panel._body.toPlainText()


def test_the_window_knows_which_worktrees_are_not_here(window, missing_worktree):
    assert window._missing_worktree_paths == {missing_worktree}


def test_opening_a_missing_worktree_explains_instead_of_trying(window, missing_worktree):
    window._switch_repo(missing_worktree)

    assert window.opened_by_factory == []
    assert _log_is_open(window)
    assert f"Cannot open {missing_worktree}: this worktree is not on this machine" in _log_text(
        window
    )


def test_opening_a_worktree_that_is_here_is_not_held_back(window, repo_path, tmp_path_factory):
    wt_path = tmp_path_factory.mktemp("wt") / "here"
    subprocess.run(
        ["git", "-C", str(repo_path), "worktree", "add", "-b", "here", str(wt_path)],
        check=True,
        capture_output=True,
    )
    window._load_worktrees_for_active_repo()

    window._switch_repo(str(wt_path.resolve()))

    assert window.opened_by_factory == [str(wt_path.resolve())]
    assert not _log_is_open(window)


def test_checking_out_a_branch_held_by_a_missing_worktree_says_where_it_is(
    window, missing_worktree
):
    branch = Branch(name="feat", is_remote=False, is_head=False, target_oid="")

    handled = window._switch_to_worktree_holding(branch)

    assert handled is True
    assert window.opened_by_factory == []
    assert _log_is_open(window)
    assert f"Branch feat is checked out in {missing_worktree}, which is not on this machine" in (
        _log_text(window)
    )
