"""Clicking a branch on a merge commit while the commit list shows a file's history.

A real repository and git's own file history: the bug lives between the two
answers git gives about a merge. Diffed against its first parent, a merge
that brought in a side branch's change to the file lists the file; the
followed file history never lists a merge at all.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pygit2
import pytest
from pygit2.enums import FileMode

from git_gui.infrastructure.pygit2 import Pygit2Repository
from git_gui.presentation.bus import QueryBus
from git_gui.presentation.models.graph_model import OID_ROLE
from git_gui.presentation.widgets.graph import PAGE_SIZE, GraphWidget


class _InlineThread:
    """Runs the worker where it was created, so its result lands at once.

    Only the graph's own reference is swapped: subprocess reads git's output
    on threads of its own, which must stay real.
    """

    def __init__(self, target=None, daemon=None, **kwargs) -> None:
        self._target = target

    def start(self) -> None:
        if self._target is not None:
            self._target()


@pytest.fixture(autouse=True)
def inline_workers(monkeypatch):
    monkeypatch.setattr(
        "git_gui.presentation.widgets.graph.threading", SimpleNamespace(Thread=_InlineThread)
    )


class _History:
    """Writes commits straight to the object store, each one a minute after the last."""

    def __init__(self, path: Path) -> None:
        self.repo = pygit2.init_repository(str(path), initial_head="master")
        self._time = 1_700_000_000

    def commit(self, message: str, files: dict[str, str], parents: list[str]) -> str:
        self._time += 60
        sig = pygit2.Signature("T", "t@example.com", self._time, 0)
        builder = self.repo.TreeBuilder()
        for name, text in files.items():
            builder.insert(name, self.repo.create_blob(text.encode()), FileMode.BLOB)
        return str(self.repo.create_commit(None, sig, sig, message, builder.write(), parents))

    def check_out(self, branch: str, tip: str) -> None:
        self.repo.references.create(f"refs/heads/{branch}", tip, force=True)
        self.repo.set_head(f"refs/heads/{branch}")
        self.repo.checkout_head(strategy=pygit2.GIT_CHECKOUT_FORCE)


def _repo_with_a_merged_pull_request(path: Path) -> str:
    """More than a page of README.md changes on master, then a pull request
    that changed README.md merged into master, which had only changed
    other.txt meanwhile. A feature branch, checked out, sits one README.md
    commit past the merge; master points at the merge. Returns the merge."""
    history = _History(path)
    files = {"README.md": "0", "other.txt": "0"}
    tip = history.commit("start", files, [])
    for i in range(1, PAGE_SIZE + 10):
        files = {**files, "README.md": str(i)}
        tip = history.commit(f"readme {i}", files, [tip])
    side = history.commit("pr: readme", {**files, "README.md": "pr"}, [tip])
    files = {**files, "other.txt": "1"}
    tip = history.commit("other", files, [tip])
    files = {**files, "README.md": "pr"}
    merge = history.commit("Merge pull request", files, [tip, side])
    history.repo.references.create("refs/heads/master", merge)
    history.check_out("feature", history.commit("feature", {**files, "README.md": "f"}, [merge]))
    return merge


def _repo_with_a_merge_that_resolved_the_file(path: Path) -> str:
    """Both sides of a merge changed README.md and the merge settled on a
    third text; more than a page of README.md changes follow it on master.
    Returns the merge."""
    history = _History(path)
    start = history.commit("start", {"README.md": "0"}, [])
    side = history.commit("side: readme", {"README.md": "side"}, [start])
    main = history.commit("main: readme", {"README.md": "main"}, [start])
    merge = history.commit("Merge side", {"README.md": "resolved"}, [main, side])
    tip = merge
    for i in range(PAGE_SIZE + 10):
        tip = history.commit(f"readme {i}", {"README.md": str(i)}, [tip])
    history.check_out("master", tip)
    return merge


def _file_history_of_readme(qtbot, path: Path) -> GraphWidget:
    """The commit list over the repo at `path`, showing README.md's history
    one page in, with get_file_history spied on from then."""
    store = MagicMock()
    store.get_repo_setting.return_value = False
    graph = GraphWidget(QueryBus.from_reader(Pygit2Repository(str(path))), MagicMock(), store)
    qtbot.addWidget(graph)
    graph.set_path_filter("README.md")
    assert graph._model.rowCount() == PAGE_SIZE and graph._has_more
    graph._queries.get_file_history = MagicMock(wraps=graph._queries.get_file_history)
    return graph


def _selected(graph: GraphWidget) -> str | None:
    return graph._model.data(graph._view.currentIndex(), OID_ROLE)


def test_a_branch_on_a_merge_commit_leaves_the_followed_file_history_without_walking_it(
    qtbot, tmp_path
):
    """master on the last pull request's merge, under a feature branch: git
    log --follow lists no merge, but the merge's first-parent diff names
    README.md, so the click paged through the file's whole history first."""
    merge = _repo_with_a_merged_pull_request(tmp_path)
    graph = _file_history_of_readme(qtbot, tmp_path)

    graph.reload_with_extra_tip(merge)

    assert graph._path_filter is None
    assert _selected(graph) == merge
    graph._queries.get_file_history.execute.assert_not_called()


def test_a_merge_that_resolved_the_file_is_found_further_down_its_unfollowed_history(
    qtbot, tmp_path
):
    """Without --follow, git lists a merge whose file differs from every
    parent, so leaving the file history at once would be wrong there."""
    merge = _repo_with_a_merge_that_resolved_the_file(tmp_path)
    graph = _file_history_of_readme(qtbot, tmp_path)
    graph._path_filter_bar._follow.setChecked(False)

    graph.reload_with_extra_tip(merge)

    assert graph._path_filter == "README.md"
    assert _selected(graph) == merge
