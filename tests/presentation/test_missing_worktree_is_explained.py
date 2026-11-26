"""A worktree with no checkout on this machine cannot be opened from here, and
when the open fails the window says why.

Such a worktree is registered in the admin dir — added from another machine
or a container, or its folder deleted — so git still lists it and the branch
it holds is still in use. Opening it used to land pygit2's "Repository not
found", which names the path and nothing else; checking out its branch here
used to switch to it, and fail the same way.

The open is still tried: what the last listing found missing is a snapshot,
and a worktree on a drive that has come back since should open.
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


def test_a_failed_open_of_a_missing_worktree_is_explained(qtbot, window, missing_worktree):
    with qtbot.waitSignal(window._repo_ready_signals.failed, timeout=2000):
        window._switch_repo(missing_worktree)

    assert window.opened_by_factory == [missing_worktree]
    assert _log_is_open(window)
    assert f"Cannot open {missing_worktree}: this worktree is not on this machine" in _log_text(
        window
    )
    assert "Repository not found" not in _log_text(window)


def test_a_missing_worktree_that_has_come_back_opens(qtbot, window, repo_path, missing_worktree):
    """The listing is a snapshot: a folder on a drive mounted again since must
    not be refused on what was true at the last listing."""
    subprocess.run(
        ["git", "-C", str(repo_path), "worktree", "add", "-f", missing_worktree, "feat"],
        check=True,
        capture_output=True,
    )

    with qtbot.waitSignal(window._repo_ready_signals.ready, timeout=2000):
        window._switch_repo(missing_worktree)

    assert window.opened_by_factory == [missing_worktree]
    assert not _log_is_open(window)


def test_opening_a_worktree_that_is_here_is_not_held_back(
    qtbot, window, repo_path, tmp_path_factory
):
    wt_path = tmp_path_factory.mktemp("wt") / "here"
    subprocess.run(
        ["git", "-C", str(repo_path), "worktree", "add", "-b", "here", str(wt_path)],
        check=True,
        capture_output=True,
    )
    window._load_worktrees_for_active_repo()

    with qtbot.waitSignal(window._repo_ready_signals.ready, timeout=2000):
        window._switch_repo(str(wt_path.resolve()))

    assert window.opened_by_factory == [str(wt_path.resolve())]
    assert not _log_is_open(window)


def test_the_worktrees_dialog_and_the_explanation_agree(qtbot, window, repo_path, tmp_path_factory):
    """A worktree whose folder went after the last listing: the dialog lists
    afresh and says "not on this machine", so Open on that row must be
    explained the same way, not with pygit2's bare error."""
    from PySide6.QtCore import QTimer

    wt_path = tmp_path_factory.mktemp("wt") / "gone-later"
    subprocess.run(
        ["git", "-C", str(repo_path), "worktree", "add", "-b", "gone-later", str(wt_path)],
        check=True,
        capture_output=True,
    )
    window._load_worktrees_for_active_repo()
    shutil.rmtree(wt_path)
    gone = str(wt_path.resolve())
    assert gone not in window._missing_worktree_paths

    def _press_open_on_the_gone_row():
        dlg = window._worktrees_dialog
        row = next(r for r in range(dlg.row_count()) if dlg.row_path(r) == gone)
        assert dlg.row_status_text(row) == "not on this machine"
        dlg.select_row(row)
        dlg.click_open()

    QTimer.singleShot(0, _press_open_on_the_gone_row)
    with qtbot.waitSignal(window._repo_ready_signals.failed, timeout=2000):
        window._open_worktrees_dialog()

    assert f"Cannot open {gone}: this worktree is not on this machine" in _log_text(window)


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
