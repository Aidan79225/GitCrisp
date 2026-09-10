"""Signal and method-contract tests for SidebarWidget.

Covers public-API regressions: single-click routing by item kind,
double-click branch checkout, context-menu action emissions, and
bus-detach model clearing. No rendering or async-reload tests here."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem
from PySide6.QtWidgets import QMenu

from git_gui.presentation.widgets.sidebar import (
    _IS_HEAD_ROLE,
    _TARGET_OID_ROLE,
    _UPSTREAM_OID_ROLE,
    SidebarWidget,
)

# -- Helpers ---------------------------------------------------------------


def _branch_item(
    name: str, oid: str, *, is_head: bool = False, upstream_oid: str | None = None
) -> QStandardItem:
    child = QStandardItem(name)
    child.setEditable(False)
    child.setData(name, Qt.UserRole)
    child.setData("branch", Qt.UserRole + 1)
    child.setData(oid, _TARGET_OID_ROLE)
    if upstream_oid:
        child.setData(upstream_oid, _UPSTREAM_OID_ROLE)
    if is_head:
        child.setData(True, _IS_HEAD_ROLE)
    return child


def _remote_branch_item(name: str, oid: str) -> QStandardItem:
    child = QStandardItem(name)
    child.setEditable(False)
    child.setData(name, Qt.UserRole)
    child.setData("remote_branch", Qt.UserRole + 1)
    child.setData(oid, _TARGET_OID_ROLE)
    return child


def _stash_item(message: str, index: int, oid: str) -> QStandardItem:
    child = QStandardItem(message)
    child.setEditable(False)
    child.setData(str(index), Qt.UserRole)
    child.setData("stash", Qt.UserRole + 1)
    child.setData(oid, _TARGET_OID_ROLE)
    return child


def _tag_item(name: str, oid: str) -> QStandardItem:
    child = QStandardItem(name)
    child.setEditable(False)
    child.setData(name, Qt.UserRole)
    child.setData("tag", Qt.UserRole + 1)
    child.setData(oid, _TARGET_OID_ROLE)
    return child


def _add_section(
    sidebar: SidebarWidget, title: str, children: list[QStandardItem]
) -> QStandardItem:
    header = QStandardItem(title)
    header.setEditable(False)
    header.setData("header", Qt.UserRole + 1)
    for c in children:
        header.appendRow(c)
    sidebar._model.appendRow(header)
    return header


def _capture_menu_actions(sidebar: SidebarWidget, item: QStandardItem) -> dict:
    """Invoke _show_context_menu for the item's index and return a dict of
    {action_text: QAction}.

    Replaces the QMenu class reference in the sidebar module's namespace
    with a local subclass whose `exec`/`exec_`/`popup` are overridden to
    no-ops. This is the most reliable way to intercept PySide6's C++-bound
    QMenu.exec — Python-level patching (`patch.object(QMenu, "exec", ...)`
    or instance-attribute shadowing) does NOT prevent the modal from
    opening, which manifests as stray top-level windows floating on the
    desktop after `pytest` completes.

    Mocks sidebar._tree.indexAt at the instance level so the handler
    resolves the pos we provide to the item's real QModelIndex."""
    from PySide6.QtCore import QPoint

    captured: list[QMenu] = []

    class _NoExecMenu(QMenu):
        """Subclass of QMenu with exec disabled. Python method resolution
        finds this override before the C++-level exec, so the menu never
        becomes visible. The sidebar's `menu.exec(pos)` call returns None
        immediately."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            captured.append(self)

        def exec(self, *args, **kwargs):
            return None

        def exec_(self, *args, **kwargs):
            return None

        def popup(self, *args, **kwargs):
            return None

    idx = sidebar._model.indexFromItem(item)
    sidebar._tree.indexAt = MagicMock(return_value=idx)

    with patch("git_gui.presentation.widgets.sidebar.QMenu", _NoExecMenu):
        sidebar._show_context_menu(QPoint(0, 0))

    assert captured, "No QMenu was constructed"
    menu = captured[-1]
    return {action.text(): action for action in menu.actions() if action.text()}


@pytest.fixture
def sidebar(qtbot):
    queries = MagicMock()
    queries.get_branches.execute.return_value = []
    queries.get_stashes.execute.return_value = []
    queries.get_tags.execute.return_value = []
    commands = MagicMock()
    w = SidebarWidget(queries, commands, remote_tag_cache=None, repo_path=None)
    qtbot.addWidget(w)
    return w, queries, commands


# -- 1. Single-click routing ----------------------------------------------


def test_single_click_local_branch_emits_branch_clicked_with_oid(sidebar, qtbot):
    w, _, _ = sidebar
    item = _branch_item("feature", "abc123")
    _add_section(w, "LOCAL BRANCHES", [item])
    idx = w._model.indexFromItem(item)

    with qtbot.waitSignal(w.branch_clicked, timeout=1000) as blocker:
        w._on_click(idx)
    assert blocker.args == ["abc123", []]


def test_single_click_local_branch_carries_its_upstream_tip(sidebar, qtbot):
    """A branch that is behind its remote has to bring the remote tip along,
    or the graph stops at the local tip and the commits the remote is holding
    ahead of it are nowhere on screen."""
    w, _, _ = sidebar
    item = _branch_item("feature", "abc123", upstream_oid="remote99")
    _add_section(w, "LOCAL BRANCHES", [item])
    idx = w._model.indexFromItem(item)

    with qtbot.waitSignal(w.branch_clicked, timeout=1000) as blocker:
        w._on_click(idx)
    assert blocker.args == ["abc123", ["remote99"]]


def test_single_click_tag_emits_tag_clicked_with_target_oid(sidebar, qtbot):
    """Tag click must emit the target oid, NOT the tag name."""
    w, _, _ = sidebar
    item = _tag_item("v1.0", "def456")
    _add_section(w, "TAGS", [item])
    idx = w._model.indexFromItem(item)

    with qtbot.waitSignal(w.tag_clicked, timeout=1000) as blocker:
        w._on_click(idx)
    assert blocker.args == ["def456"]


def test_single_click_stash_emits_stash_clicked_with_oid(sidebar, qtbot):
    w, _, _ = sidebar
    item = _stash_item("my stash", index=0, oid="789abc")
    _add_section(w, "STASHES", [item])
    idx = w._model.indexFromItem(item)

    with qtbot.waitSignal(w.stash_clicked, timeout=1000) as blocker:
        w._on_click(idx)
    assert blocker.args == ["789abc"]


# -- 2. Double-click branch -----------------------------------------------


def test_double_click_local_branch_emits_checkout_branch_requested(sidebar, qtbot):
    w, _, commands = sidebar
    item = _branch_item("feature", "abc123")
    _add_section(w, "LOCAL BRANCHES", [item])
    idx = w._model.indexFromItem(item)

    with qtbot.waitSignal(w.checkout_branch_requested, timeout=1000) as blocker:
        w._on_double_click(idx)

    commands.checkout.execute.assert_not_called()
    assert blocker.args == ["feature"]


def test_double_click_branch_emits_checkout_branch_requested(qtbot):
    """Double-clicking a local branch emits the new unified signal."""
    queries, commands = MagicMock(), MagicMock()
    sidebar = SidebarWidget(queries=queries, commands=commands)
    qtbot.addWidget(sidebar)
    item = _branch_item("feature/foo", "abc")
    sidebar._model.appendRow(item)
    received: list[str] = []
    sidebar.checkout_branch_requested.connect(received.append)

    sidebar._on_double_click(sidebar._model.indexFromItem(item))

    assert received == ["feature/foo"]
    commands.checkout.execute.assert_not_called()


def test_double_click_remote_branch_emits_checkout_branch_requested(qtbot):
    """Double-clicking a remote branch emits the same signal (previously did nothing)."""
    queries, commands = MagicMock(), MagicMock()
    sidebar = SidebarWidget(queries=queries, commands=commands)
    qtbot.addWidget(sidebar)
    item = _remote_branch_item("origin/feature/foo", "abc")
    sidebar._model.appendRow(item)
    received: list[str] = []
    sidebar.checkout_branch_requested.connect(received.append)

    sidebar._on_double_click(sidebar._model.indexFromItem(item))

    assert received == ["origin/feature/foo"]
    commands.checkout.execute.assert_not_called()


def test_double_click_stash_does_not_emit_checkout(qtbot):
    """Non-branch items must not trigger the checkout signal."""
    queries, commands = MagicMock(), MagicMock()
    sidebar = SidebarWidget(queries=queries, commands=commands)
    qtbot.addWidget(sidebar)
    # Use existing _stash_item helper from the top of the file
    item = _stash_item("WIP", 0, "deadbeef")
    sidebar._model.appendRow(item)
    received: list[str] = []
    sidebar.checkout_branch_requested.connect(received.append)

    sidebar._on_double_click(sidebar._model.indexFromItem(item))

    assert received == []


# -- 3. Context menu: remote-branch fetch parses remote name --------------


def test_remote_branch_fetch_menu_emits_remote_name_only(sidebar, qtbot):
    w, _, _ = sidebar
    item = _remote_branch_item("origin/feature", "abc123")
    _add_section(w, "REMOTE BRANCHES", [item])

    actions = _capture_menu_actions(w, item)
    assert "Fetch" in actions

    with qtbot.waitSignal(w.fetch_requested, timeout=1000) as blocker:
        actions["Fetch"].trigger()
    assert blocker.args == ["origin"]


# -- 4. Context menu: stash actions emit correct index --------------------


def test_stash_pop_menu_emits_correct_index(sidebar, qtbot):
    w, _, _ = sidebar
    item = _stash_item("third stash", index=2, oid="0xabc")
    _add_section(w, "STASHES", [item])

    actions = _capture_menu_actions(w, item)
    assert "Pop" in actions

    with qtbot.waitSignal(w.stash_pop_requested, timeout=1000) as blocker:
        actions["Pop"].trigger()
    assert blocker.args == [2]


def test_stash_apply_menu_emits_correct_index(sidebar, qtbot):
    w, _, _ = sidebar
    item = _stash_item("third stash", index=2, oid="0xabc")
    _add_section(w, "STASHES", [item])

    actions = _capture_menu_actions(w, item)
    assert "Apply" in actions

    with qtbot.waitSignal(w.stash_apply_requested, timeout=1000) as blocker:
        actions["Apply"].trigger()
    assert blocker.args == [2]


def test_stash_drop_menu_emits_correct_index(sidebar, qtbot):
    w, _, _ = sidebar
    item = _stash_item("third stash", index=2, oid="0xabc")
    _add_section(w, "STASHES", [item])

    actions = _capture_menu_actions(w, item)
    assert "Drop" in actions

    with qtbot.waitSignal(w.stash_drop_requested, timeout=1000) as blocker:
        actions["Drop"].trigger()
    assert blocker.args == [2]


# -- 5. Context menu: tag delete emits tag name ---------------------------


def test_tag_delete_menu_emits_tag_name(sidebar, qtbot):
    w, _, _ = sidebar
    item = _tag_item("v2.1", "0xdef")
    _add_section(w, "TAGS", [item])

    actions = _capture_menu_actions(w, item)
    assert "Delete" in actions

    with qtbot.waitSignal(w.tag_delete_requested, timeout=1000) as blocker:
        actions["Delete"].trigger()
    assert blocker.args == ["v2.1"]


# -- 7. Context menu: remote-branch delete emits remote and branch -----


def test_remote_branch_delete_menu_emits_remote_and_branch(sidebar, qtbot):
    w, _, _ = sidebar
    item = _remote_branch_item("origin/feature", "abc123")
    _add_section(w, "REMOTE BRANCHES", [item])

    actions = _capture_menu_actions(w, item)
    assert "Delete" in actions

    with qtbot.waitSignal(w.remote_branch_delete_requested, timeout=1000) as blocker:
        actions["Delete"].trigger()
    assert blocker.args == ["origin", "feature"]


def test_remote_branch_delete_handles_slash_in_branch_name(sidebar, qtbot):
    """Branch names containing '/' must be preserved after splitting off
    the remote prefix (e.g. origin/feature/foo → remote=origin, branch=feature/foo)."""
    w, _, _ = sidebar
    item = _remote_branch_item("origin/feature/foo", "abc123")
    _add_section(w, "REMOTE BRANCHES", [item])

    actions = _capture_menu_actions(w, item)

    with qtbot.waitSignal(w.remote_branch_delete_requested, timeout=1000) as blocker:
        actions["Delete"].trigger()
    assert blocker.args == ["origin", "feature/foo"]


# -- 6. Bus detach clears model -------------------------------------------


def test_set_buses_none_clears_model(sidebar):
    w, _, _ = sidebar
    _add_section(w, "LOCAL BRANCHES", [_branch_item("main", "aaa")])
    assert w._model.rowCount() == 1

    w.set_buses(None, None)
    assert w._model.rowCount() == 0
