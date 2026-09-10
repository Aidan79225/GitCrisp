"""End-to-end journeys through the real stack.

Each test drives the window the way a user drives it — clicking buttons,
selecting rows, answering dialogs — and then checks both what the UI shows and
what the repository on disk contains. Nothing here is mocked except the modal
dialogs a headless run cannot answer.
"""

from __future__ import annotations

from PySide6.QtCore import Qt

from git_gui.domain.entities import WORKING_TREE_OID
from git_gui.presentation.main_window import branch_flows
from tests.e2e.conftest import TIMEOUT
from tests.e2e.helpers import (
    graph_oids,
    head_branch,
    head_message,
    head_oid,
    head_tree_paths,
    log_lines,
    sidebar_head_branch,
    sidebar_section,
    working_tree_paths,
)


def test_cold_launch_renders_history_and_branches(qtbot, make_repo, make_window):
    """The launch path main.py takes: real repo in, populated window out."""
    repo = make_repo("solo", commits=3)

    window = make_window(repo)

    qtbot.waitUntil(lambda: len(graph_oids(window)) == 3, timeout=TIMEOUT)
    assert graph_oids(window)[0] == head_oid(repo)  # newest first
    qtbot.waitUntil(
        lambda: sidebar_section(window, "LOCAL BRANCHES") == ["master"],
        timeout=TIMEOUT,
    )
    assert sidebar_head_branch(window) == "master"
    assert window.windowTitle() == f"GitCrisp — {repo}"


def test_launch_without_a_repo_shows_an_empty_window(qtbot, make_window):
    """First run, or every stored repo pruned — the window still opens."""
    window = make_window(None)

    assert window.windowTitle() == "GitCrisp"
    assert graph_oids(window) == []
    assert sidebar_section(window, "LOCAL BRANCHES") == []
    assert window._right_stack.currentIndex() == 0
    qtbot.wait(100)  # nothing queued blows up once the event loop turns


def test_stage_and_commit_journey(qtbot, make_repo, make_window):
    """Edit a file, stage it, commit it — and the commit really lands."""
    repo = make_repo("work", commits=1)
    window = make_window(repo)
    qtbot.waitUntil(lambda: len(graph_oids(window)) == 1, timeout=TIMEOUT)

    (repo / "feature.py").write_text("print('hello')\n")
    window._reload()  # what F5 and the change detector do

    # The dirty working tree shows up as its own row at the top of the list.
    qtbot.waitUntil(lambda: WORKING_TREE_OID in graph_oids(window), timeout=TIMEOUT)
    window._graph.scroll_to_oid(WORKING_TREE_OID, select=True)
    assert window._right_stack.currentIndex() == 1

    working_tree = window._working_tree
    qtbot.waitUntil(lambda: working_tree_paths(window) == ["feature.py"], timeout=TIMEOUT)

    qtbot.mouseClick(working_tree._btn_stage_all, Qt.LeftButton)
    working_tree._msg_edit.setPlainText("Add the feature")
    qtbot.mouseClick(working_tree._btn_commit, Qt.LeftButton)

    assert head_message(repo) == "Add the feature"
    assert head_tree_paths(repo) == ["feature.py", "file0.txt"]
    qtbot.waitUntil(lambda: graph_oids(window)[0] == head_oid(repo), timeout=TIMEOUT)
    assert any(line.endswith('Commit: "Add the feature"') for line in log_lines(window))


def test_create_branch_then_switch_back(qtbot, make_repo, make_window, monkeypatch):
    """Branch off a commit, land on it, and switch back through the sidebar."""
    repo = make_repo("branchy", commits=2)
    window = make_window(repo)
    qtbot.waitUntil(lambda: len(graph_oids(window)) == 2, timeout=TIMEOUT)

    class _NamesTheBranch:
        @staticmethod
        def getText(*args, **kwargs):
            return ("feature", True)

    monkeypatch.setattr(branch_flows, "QInputDialog", _NamesTheBranch)
    window._graph.create_branch_requested.emit(head_oid(repo))

    assert head_branch(repo) == "feature"
    qtbot.waitUntil(lambda: sidebar_head_branch(window) == "feature", timeout=TIMEOUT)
    assert sidebar_section(window, "LOCAL BRANCHES") == ["feature", "master"]

    window._sidebar.checkout_branch_requested.emit("master")

    assert head_branch(repo) == "master"
    qtbot.waitUntil(lambda: sidebar_head_branch(window) == "master", timeout=TIMEOUT)


def test_switching_repos_rebuilds_the_session(qtbot, make_repo, make_window):
    """Repo switching opens a genuinely new session on a worker thread."""
    first = make_repo("first", commits=1)
    second = make_repo("second", commits=2)
    window = make_window(first)
    qtbot.waitUntil(lambda: graph_oids(window) == [head_oid(first)], timeout=TIMEOUT)
    window._repo_store.add_open(str(second))

    window._repo_list.repo_switch_requested.emit(str(second))

    qtbot.waitUntil(lambda: window._repo_path == str(second), timeout=TIMEOUT)
    qtbot.waitUntil(lambda: len(graph_oids(window)) == 2, timeout=TIMEOUT)
    assert graph_oids(window)[0] == head_oid(second)
    assert window.windowTitle() == f"GitCrisp — {second}"
    assert window._repo_store.get_active() == str(second)
    # The new session is a live one, not the old repo's buses reused.
    assert window._queries.get_head_oid.execute() == head_oid(second)
