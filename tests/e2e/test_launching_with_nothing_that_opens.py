"""A launch where no stored repo opens leaves every repo in the list clickable.

The repo the last session left active stays active in the store when it will
not open, so that it is tried first again next time. The repo list drew the
store's active repo as the one on screen, and ignores clicks on that row: with
nothing open, the user could neither retry it nor see why it failed, until a
restart. The same held for a repo on a drive or share that was out of reach at
launch and came back.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt

import main as app_main
from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.presentation.widgets.repo_list import _IS_ACTIVE_ROLE


@pytest.fixture
def start_window(qtbot, tmp_path):
    """The startup window, over a store whose only open repo is *repo*, active."""
    windows = []

    def _start(repo: Path):
        store = JsonRepoStore(tmp_path / "repos.json")
        store.load()
        store.add_open(str(repo))
        store.set_active(str(repo))
        window = app_main._open_window(store, JsonRemoteTagCache(tmp_path / "remote_tags"))
        qtbot.addWidget(window)
        windows.append(window)
        return window

    yield _start

    for window in windows:
        window._stop_change_detector()
    qtbot.wait(200)


def _broken_repo(make_repo, _tmp_path: Path) -> Path:
    """A repo discover_repository accepts but pygit2 will not open."""
    path = make_repo("broken")
    (path / ".git" / "config").write_text("[core\n", encoding="utf-8")
    return path


def _out_of_reach(_make_repo, tmp_path: Path) -> Path:
    """A repo on a drive that is not plugged in."""
    return tmp_path / "unplugged-drive" / "repo"


def _repo_row(window, path: Path):
    model = window._repo_list._model
    for section in (model.item(row) for row in range(model.rowCount())):
        for row in range(section.rowCount()):
            if section.child(row).data(Qt.UserRole) == str(path):
                return section.child(row).index()
    raise AssertionError(f"no repo row for {path}")


@pytest.mark.parametrize("stored", [_broken_repo, _out_of_reach])
def test_a_sole_repo_that_did_not_open_is_not_drawn_as_open(
    make_repo, tmp_path, start_window, stored
):
    repo = stored(make_repo, tmp_path)

    window = start_window(repo)

    assert window._repo_path is None
    assert not _repo_row(window, repo).data(_IS_ACTIVE_ROLE)


@pytest.mark.parametrize("stored", [_broken_repo, _out_of_reach])
def test_a_sole_repo_that_did_not_open_can_be_clicked(
    make_repo, tmp_path, start_window, qtbot, stored
):
    """Clicking it is how the user retries it and sees why it failed."""
    repo = stored(make_repo, tmp_path)
    window = start_window(repo)

    with qtbot.waitSignal(window._repo_list.repo_switch_requested, timeout=1000) as switch:
        window._repo_list._on_item_clicked(_repo_row(window, repo))

    assert switch.args == [str(repo)]
