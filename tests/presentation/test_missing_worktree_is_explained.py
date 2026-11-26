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
from pathlib import Path

import pytest

from git_gui.domain.entities import Branch
from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.presentation.main_window import MainWindow


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _add_worktree(repo_path: Path, tmp_path_factory, branch: str) -> Path:
    wt_path = tmp_path_factory.mktemp("wt") / branch
    _git(repo_path, "worktree", "add", "-b", branch, str(wt_path))
    return wt_path


@pytest.fixture
def missing_worktree(repo_path, tmp_path_factory) -> str:
    """A linked worktree of repo_path on branch feat whose folder is gone."""
    wt_path = _add_worktree(repo_path, tmp_path_factory, "feat")
    shutil.rmtree(wt_path)
    return str(wt_path.resolve())


@pytest.fixture
def worktree_gone_after_the_load(window, repo_path, tmp_path_factory) -> str:
    """A linked worktree the window listed, whose folder went after that listing."""
    wt_path = _add_worktree(repo_path, tmp_path_factory, "gone-later")
    window._load_worktrees_for_active_repo()
    shutil.rmtree(wt_path)
    gone = str(wt_path.resolve())
    assert gone not in window._missing_worktree_paths
    return gone


@pytest.fixture
def opened_paths() -> list[str]:
    """Every path the window's session factory was asked to open."""
    return []


@pytest.fixture
def window(qtbot, repo_path, missing_worktree, opened_paths, tmp_path_factory):
    """The window on repo_path, with its worktrees loaded — the missing one among them."""
    from main import _open_session

    def _session_factory(path: str):
        opened_paths.append(path)
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
    qtbot.addWidget(w)
    w._load_worktrees_for_active_repo()
    return w


def _log_is_open(window) -> bool:
    return not window._log_panel._body.isHidden()


def _log_text(window) -> str:
    return window._log_panel._body.toPlainText()


def test_the_window_knows_which_worktrees_are_not_here(window, missing_worktree):
    assert window._missing_worktree_paths == {missing_worktree}


def test_a_failed_open_of_a_missing_worktree_is_explained(
    qtbot, window, missing_worktree, opened_paths
):
    with qtbot.waitSignal(window._repo_ready_signals.failed, timeout=2000):
        window._switch_repo(missing_worktree)

    assert opened_paths == [missing_worktree]
    assert _log_is_open(window)
    assert f"Cannot open {missing_worktree}: this worktree is not on this machine" in _log_text(
        window
    )


def test_a_missing_worktree_that_has_come_back_opens(
    qtbot, window, repo_path, missing_worktree, opened_paths
):
    """The listing is a snapshot: a folder on a drive mounted again since must
    not be refused on what was true at the last listing."""
    _git(repo_path, "worktree", "add", "-f", missing_worktree, "feat")

    with qtbot.waitSignal(window._repo_ready_signals.ready, timeout=2000):
        window._switch_repo(missing_worktree)

    assert opened_paths == [missing_worktree]
    assert not _log_is_open(window)


def test_opening_a_worktree_that_is_here_is_not_held_back(
    qtbot, window, repo_path, opened_paths, tmp_path_factory
):
    wt_path = _add_worktree(repo_path, tmp_path_factory, "here")
    window._load_worktrees_for_active_repo()

    with qtbot.waitSignal(window._repo_ready_signals.ready, timeout=2000):
        window._switch_repo(str(wt_path.resolve()))

    assert opened_paths == [str(wt_path.resolve())]
    assert not _log_is_open(window)


def test_a_worktree_deleted_after_the_load_is_explained_when_its_row_is_clicked(
    qtbot, window, worktree_gone_after_the_load
):
    """Nothing lists between the repo load and a click on the sidebar row, so
    the failed open lists again: the reason is given and the row redrawn as
    not on this machine."""
    gone = worktree_gone_after_the_load

    with qtbot.waitSignal(window._repo_ready_signals.failed, timeout=2000):
        window._switch_repo(gone)

    assert f"Cannot open {gone}: this worktree is not on this machine" in _log_text(window)
    assert gone in window._missing_worktree_paths


def test_the_worktrees_dialog_and_the_explanation_agree(
    qtbot, window, worktree_gone_after_the_load
):
    """The dialog lists afresh and says "not on this machine", so Open on that
    row must be explained the same way, not with pygit2's bare error."""
    from PySide6.QtCore import QTimer

    gone = worktree_gone_after_the_load

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
    window, missing_worktree, opened_paths
):
    branch = Branch(name="feat", is_remote=False, is_head=False, target_oid="")

    handled = window._switch_to_worktree_holding(branch)

    assert handled is True
    assert opened_paths == []
    assert _log_is_open(window)
    assert f"Branch feat is checked out in {missing_worktree}, which is not on this machine" in (
        _log_text(window)
    )


def test_the_add_worktree_dialogs_switch_and_the_explanation_agree(
    qtbot, window, worktree_gone_after_the_load, monkeypatch
):
    """Add Worktree lists afresh too, and offers "Switch to That Worktree" for
    a branch a worktree holds; that switch failing must be explained the same
    way."""
    from git_gui.presentation.dialogs.add_worktree_dialog import AddWorktreeDialog

    gone = worktree_gone_after_the_load
    shown: list[AddWorktreeDialog] = []
    monkeypatch.setattr(AddWorktreeDialog, "exec", lambda self: shown.append(self) or 0)

    window._open_add_worktree_dialog(preselect_branch="gone-later", default_create=False)
    with qtbot.waitSignal(window._repo_ready_signals.failed, timeout=2000):
        shown[0]._on_switch_to_existing()

    assert f"Cannot open {gone}: this worktree is not on this machine" in _log_text(window)
