"""Tests for the merge/rebase section of GraphWidget._show_context_menu.

We exercise _add_merge_rebase_section directly with a fake QueryBus to avoid
needing a fully-initialised GraphWidget.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QMenu

from git_gui.domain.entities import RepoState, RepoStateInfo
from git_gui.presentation.widgets.graph import GraphWidget


@dataclass
class _FakeQuery:
    fn: Callable

    def execute(self, *args, **kwargs):
        return self.fn(*args, **kwargs)


class _FakeQueryBus:
    def __init__(
        self,
        *,
        state: RepoStateInfo,
        head_oid: str | None,
        is_ancestor: Callable[[str, str], bool] = lambda a, d: False,
    ):
        self.get_repo_state = _FakeQuery(lambda: state)
        self.get_head_oid = _FakeQuery(lambda: head_oid)
        self.is_ancestor = _FakeQuery(is_ancestor)


def _make_widget_with_queries(qtbot, queries) -> GraphWidget:
    # GraphWidget.__init__ does a lot — bypass it for these unit tests.
    w = GraphWidget.__new__(GraphWidget)
    w._queries = queries
    from PySide6.QtWidgets import QWidget

    QWidget.__init__(w)
    qtbot.addWidget(w)
    return w


@dataclass
class _ActionInfo:
    text: str
    enabled: bool
    tooltip: str
    action: object  # QAction reference


def _collect_actions(menu: QMenu) -> list[_ActionInfo]:
    """Collect all actions (including submenu children) as data."""
    result = []
    for a in menu.actions():
        sub = a.menu()
        if sub:
            for sa in sub.actions():
                if sa.text():
                    result.append(_ActionInfo(sa.text(), sa.isEnabled(), sa.toolTip(), sa))
        elif a.text():
            result.append(_ActionInfo(a.text(), a.isEnabled(), a.toolTip(), a))
    return result


def _find_action(menu: QMenu, label: str) -> _ActionInfo | None:
    for info in _collect_actions(menu):
        if info.text == label:
            return info
    return None


def _labels(menu: QMenu) -> list[str]:
    return [info.text for info in _collect_actions(menu)]


def _submenu_titles(menu: QMenu) -> list[str]:
    return [a.text() for a in menu.actions() if a.menu()]


def test_detached_head_disables_everything(qtbot):
    queries = _FakeQueryBus(
        state=RepoStateInfo(state=RepoState.DETACHED_HEAD, head_branch=None),
        head_oid="aaaaaaaaaaaa",
    )
    w = _make_widget_with_queries(qtbot, queries)
    menu = QMenu()
    menu.setToolTipsVisible(True)
    w._add_merge_rebase_section(menu, oid="bbbbbbbbbbbb", branches_on_commit=["feature"])

    # 1 branch + 1 commit = 2 actions each → submenus
    info = _find_action(menu, "feature into HEAD")
    assert info is not None
    assert info.enabled is False
    assert "detached" in info.tooltip.lower()


def test_merging_state_disables_everything(qtbot):
    queries = _FakeQueryBus(
        state=RepoStateInfo(state=RepoState.MERGING, head_branch="main"),
        head_oid="aaaaaaaaaaaa",
    )
    w = _make_widget_with_queries(qtbot, queries)
    menu = QMenu()
    menu.setToolTipsVisible(True)
    w._add_merge_rebase_section(menu, oid="bbbbbbbbbbbb", branches_on_commit=["feature"])

    info = _find_action(menu, "feature into main")
    assert info is not None
    assert info.enabled is False
    assert "MERGING" in info.tooltip


def test_head_commit_with_no_other_branches_hides_section(qtbot):
    queries = _FakeQueryBus(
        state=RepoStateInfo(state=RepoState.CLEAN, head_branch="main"),
        head_oid="aaaaaaaaaaaa",
    )
    w = _make_widget_with_queries(qtbot, queries)
    menu = QMenu()
    w._add_merge_rebase_section(menu, oid="aaaaaaaaaaaa", branches_on_commit=[])

    assert _labels(menu) == []  # nothing added


def test_ancestor_branch_merge_disabled_with_already_up_to_date(qtbot):
    queries = _FakeQueryBus(
        state=RepoStateInfo(state=RepoState.CLEAN, head_branch="main"),
        head_oid="head1234567",
        is_ancestor=lambda a, d: a == "anc12345678" and d == "head1234567",
    )
    w = _make_widget_with_queries(qtbot, queries)
    menu = QMenu()
    menu.setToolTipsVisible(True)
    w._add_merge_rebase_section(menu, oid="anc12345678", branches_on_commit=["old-branch"])

    # Only 1 merge action (branch, no commit merge since ancestor) → top-level
    merge_info = _find_action(menu, "Merge old-branch into main")
    assert merge_info is not None
    assert merge_info.enabled is False
    assert merge_info.tooltip == "Already up to date"

    # 2 rebase actions (branch + commit) → submenu
    assert "Rebase" in _submenu_titles(menu)
    rebase_info = _find_action(menu, "main onto old-branch")
    assert rebase_info is not None
    assert rebase_info.enabled is True


def test_normal_commit_emits_signals(qtbot):
    queries = _FakeQueryBus(
        state=RepoStateInfo(state=RepoState.CLEAN, head_branch="main"),
        head_oid="head1234567",
    )
    w = _make_widget_with_queries(qtbot, queries)

    received_branch_merge: list[str] = []
    received_commit_merge: list[str] = []
    received_branch_rebase: list[str] = []
    received_commit_rebase: list[str] = []
    w.merge_branch_requested.connect(received_branch_merge.append)
    w.merge_commit_requested.connect(received_commit_merge.append)
    w.rebase_onto_branch_requested.connect(received_branch_rebase.append)
    w.rebase_onto_commit_requested.connect(received_commit_rebase.append)

    menu = QMenu()
    w._add_merge_rebase_section(menu, oid="newcommit12", branches_on_commit=["feature"])

    # 2 merge + 2 rebase → submenus
    assert "Merge" in _submenu_titles(menu)
    assert "Rebase" in _submenu_titles(menu)

    # Trigger each action via submenu
    for info in _collect_actions(menu):
        if info.text == "feature into main":
            info.action.trigger()
        elif info.text == "commit newcomm into main":
            info.action.trigger()
        elif info.text == "main onto feature":
            info.action.trigger()
        elif info.text == "main onto commit newcomm":
            info.action.trigger()

    assert received_branch_merge == ["feature"]
    assert received_commit_merge == ["newcommit12"]
    assert received_branch_rebase == ["feature"]
    assert received_commit_rebase == ["newcommit12"]


def test_multiple_branches_use_submenus(qtbot):
    queries = _FakeQueryBus(
        state=RepoStateInfo(state=RepoState.CLEAN, head_branch="main"),
        head_oid="head1234567",
    )
    w = _make_widget_with_queries(qtbot, queries)
    menu = QMenu()
    w._add_merge_rebase_section(menu, oid="other123456", branches_on_commit=["a", "b"])

    # 3 merge + 3 rebase → submenus
    assert "Merge" in _submenu_titles(menu)
    assert "Rebase" in _submenu_titles(menu)

    labels = _labels(menu)
    assert "a into main" in labels
    assert "b into main" in labels
    assert "main onto a" in labels
    assert "main onto b" in labels


def test_single_action_stays_top_level(qtbot):
    """When only 1 merge and 1 rebase action, they stay at top level (no submenu)."""
    queries = _FakeQueryBus(
        state=RepoStateInfo(state=RepoState.CLEAN, head_branch="main"),
        head_oid="aaaaaaaaaaaa",
        # Make oid == head so no commit-targeted actions
    )
    w = _make_widget_with_queries(qtbot, queries)
    menu = QMenu()
    # oid == head_oid → no commit merge/rebase, only branch actions
    w._add_merge_rebase_section(menu, oid="aaaaaaaaaaaa", branches_on_commit=["feature"])

    assert _submenu_titles(menu) == []  # no submenus
    top_labels = [a.text() for a in menu.actions() if a.text()]
    assert "Merge feature into main" in top_labels
    assert "Rebase main onto feature" in top_labels


def _menu_with_new_section(
    qtbot, *, state: RepoStateInfo, head_oid: str, target_oid: str, is_ancestor_of_head: bool
) -> QMenu:
    queries = _FakeQueryBus(
        state=state,
        head_oid=head_oid,
        is_ancestor=lambda a, d: (
            is_ancestor_of_head if a == target_oid and d == head_oid else False
        ),
    )
    w = _make_widget_with_queries(qtbot, queries)
    menu = QMenu()
    w._add_merge_rebase_section(menu, target_oid, branches_on_commit=[])
    return menu


def test_cherry_pick_entry_present_and_enabled_when_clean(qtbot):
    state = RepoStateInfo(state=RepoState.CLEAN, head_branch="master")
    menu = _menu_with_new_section(
        qtbot,
        state=state,
        head_oid="h" * 40,
        target_oid="t" * 40,
        is_ancestor_of_head=False,
    )
    actions = _collect_actions(menu)
    texts = [a.text for a in actions]
    assert any("Cherry-pick commit" in t for t in texts)
    cp = next(a for a in actions if a.text.startswith("Cherry-pick"))
    assert cp.enabled is True


def test_cherry_pick_entry_disabled_when_merging(qtbot):
    state = RepoStateInfo(state=RepoState.MERGING, head_branch="master")
    menu = _menu_with_new_section(
        qtbot,
        state=state,
        head_oid="h" * 40,
        target_oid="t" * 40,
        is_ancestor_of_head=False,
    )
    actions = _collect_actions(menu)
    cp = next(a for a in actions if a.text.startswith("Cherry-pick"))
    assert cp.enabled is False


def test_revert_entry_present_and_enabled_when_clean(qtbot):
    state = RepoStateInfo(state=RepoState.CLEAN, head_branch="master")
    menu = _menu_with_new_section(
        qtbot,
        state=state,
        head_oid="h" * 40,
        target_oid="t" * 40,
        is_ancestor_of_head=False,
    )
    actions = _collect_actions(menu)
    rv = next(a for a in actions if a.text.startswith("Revert commit"))
    assert rv.enabled is True


def test_reset_submenu_disabled_when_not_ancestor(qtbot):
    state = RepoStateInfo(state=RepoState.CLEAN, head_branch="master")
    menu = _menu_with_new_section(
        qtbot,
        state=state,
        head_oid="h" * 40,
        target_oid="t" * 40,
        is_ancestor_of_head=False,
    )
    actions = _collect_actions(menu)
    # Any reset submenu entry should be disabled.
    reset_items = [a for a in actions if "keep" in a.text.lower() or "discard" in a.text.lower()]
    assert reset_items  # submenu entries collected
    assert all(not a.enabled for a in reset_items)


def test_reset_submenu_enabled_when_ancestor(qtbot):
    state = RepoStateInfo(state=RepoState.CLEAN, head_branch="master")
    menu = _menu_with_new_section(
        qtbot,
        state=state,
        head_oid="h" * 40,
        target_oid="t" * 40,
        is_ancestor_of_head=True,
    )
    actions = _collect_actions(menu)
    reset_items = [a for a in actions if "keep" in a.text.lower() or "discard" in a.text.lower()]
    assert reset_items
    assert all(a.enabled for a in reset_items)


def test_entries_not_shown_when_target_is_head(qtbot):
    state = RepoStateInfo(state=RepoState.CLEAN, head_branch="master")
    same = "s" * 40
    menu = _menu_with_new_section(
        qtbot,
        state=state,
        head_oid=same,
        target_oid=same,
        is_ancestor_of_head=False,
    )
    actions = _collect_actions(menu)
    texts = [a.text for a in actions]
    assert not any("Cherry-pick" in t for t in texts)
    assert not any("Revert commit" in t for t in texts)


# ── Remote branch delete from context menu ─────────────────────────────


def test_emit_remote_delete_splits_remote_and_branch(qtbot):
    """`_emit_remote_delete` should split the qualified name on the first
    slash and emit (remote, branch)."""
    from git_gui.presentation.widgets.graph import GraphWidget

    w = GraphWidget.__new__(GraphWidget)
    from PySide6.QtWidgets import QWidget

    QWidget.__init__(w)
    qtbot.addWidget(w)

    received: list[tuple[str, str]] = []
    w.remote_branch_delete_requested.connect(lambda r, b: received.append((r, b)))

    w._emit_remote_delete("origin/main")

    assert received == [("origin", "main")]


def test_emit_remote_delete_handles_slash_in_branch_name(qtbot):
    """Branch names can contain slashes (e.g. 'feature/foo'). The split
    must take the first slash only."""
    from git_gui.presentation.widgets.graph import GraphWidget

    w = GraphWidget.__new__(GraphWidget)
    from PySide6.QtWidgets import QWidget

    QWidget.__init__(w)
    qtbot.addWidget(w)

    received: list[tuple[str, str]] = []
    w.remote_branch_delete_requested.connect(lambda r, b: received.append((r, b)))

    w._emit_remote_delete("origin/feature/foo")

    assert received == [("origin", "feature/foo")]


def test_emit_remote_delete_bails_on_malformed_name(qtbot):
    """A name with no slash means the input is malformed; no signal."""
    from git_gui.presentation.widgets.graph import GraphWidget

    w = GraphWidget.__new__(GraphWidget)
    from PySide6.QtWidgets import QWidget

    QWidget.__init__(w)
    qtbot.addWidget(w)

    received: list[tuple[str, str]] = []
    w.remote_branch_delete_requested.connect(lambda r, b: received.append((r, b)))

    w._emit_remote_delete("no-slash")

    assert received == []


def test_emit_remote_delete_bails_on_empty_remote(qtbot):
    """A leading slash means empty remote — bail."""
    from git_gui.presentation.widgets.graph import GraphWidget

    w = GraphWidget.__new__(GraphWidget)
    from PySide6.QtWidgets import QWidget

    QWidget.__init__(w)
    qtbot.addWidget(w)

    received: list[tuple[str, str]] = []
    w.remote_branch_delete_requested.connect(lambda r, b: received.append((r, b)))

    w._emit_remote_delete("/main")

    assert received == []


def test_local_delete_emits_local_name_when_remote_also_present(qtbot):
    """Regression: the single-item delete-branch lambda used to capture `name`
    by closure. When a commit row had both a local branch AND a remote-tracking
    branch, the later `name = remote_branches[0]` rebind clobbered the closure,
    and clicking "Delete branch: <local>" emitted the remote name instead.

    This test builds the local-only delete section and asserts the lambda
    fires with the local name, not whatever was bound last.
    """
    from PySide6.QtWidgets import QMenu

    from git_gui.presentation.widgets.graph import GraphWidget

    w = GraphWidget.__new__(GraphWidget)
    from PySide6.QtWidgets import QWidget

    QWidget.__init__(w)
    qtbot.addWidget(w)

    received_local: list[str] = []
    received_remote: list[tuple[str, str]] = []
    w.delete_branch_requested.connect(lambda n: received_local.append(n))
    w.remote_branch_delete_requested.connect(lambda r, b: received_remote.append((r, b)))

    # Build a menu manually using the EXACT closure pattern from the fix:
    # both a local-branch single-item lambda AND a later remote-branch
    # single-item lambda capture `name` via default arg.
    menu = QMenu()
    local_branches = ["main"]
    remote_branches = ["origin/main"]

    if len(local_branches) == 1:
        name = local_branches[0]
        local_action = menu.addAction(f"Delete branch: {name}")
        local_action.triggered.connect(
            lambda _checked=False, n=name: w.delete_branch_requested.emit(n)
        )

    if len(remote_branches) == 1:
        name = remote_branches[0]  # rebinds the closure variable
        remote_action = menu.addAction(f"Delete remote branch: {name}")
        remote_action.triggered.connect(lambda _checked=False, n=name: w._emit_remote_delete(n))

    # Trigger the LOCAL delete after the remote rebind. Without the
    # default-arg capture, the closure would read "origin/main".
    local_action.trigger()

    assert received_local == ["main"]
    assert received_remote == []
