"""Worktree children rendering and context menus in RepoListWidget."""

from __future__ import annotations

import os

import pytest
from PySide6.QtCore import Qt

from git_gui.domain.entities import Worktree
from git_gui.presentation.widgets.repo_list import (
    _IS_ACTIVE_ROLE,
    _KIND_ROLE,
    RepoListWidget,
    _RowKind,
)


class _FakeStore:
    def __init__(self, open_=None, recent=None, active=None):
        self._open = list(open_ or [])
        self._recent = list(recent or [])
        self._active = active

    def load(self):
        pass

    def save(self):
        pass

    def get_open_repos(self):
        return list(self._open)

    def get_recent_repos(self):
        return list(self._recent)

    def get_active(self):
        return self._active

    def add_open(self, p, after=None):
        if p in self._open:
            return
        if after and after in self._open:
            self._open.insert(self._open.index(after) + 1, p)
        else:
            self._open.append(p)

    def close_repo(self, p):
        if p in self._open:
            self._open.remove(p)

    def remove_recent(self, p):
        if p in self._recent:
            self._recent.remove(p)

    def set_active(self, p):
        self._active = p

    def set_open_order(self, paths):
        self._open = list(paths)


def _wt(path, branch="feat", locked=False):
    return Worktree(
        path=path,
        branch=branch,
        head_sha="abc",
        is_locked=locked,
        lock_reason=None,
        is_bare=False,
        is_main=False,
    )


# ── Task 10: nesting ───────────────────────────────────────────────────────


def test_active_repo_worktrees_render_as_children(qtbot):
    store = _FakeStore(open_=["/tmp/myrepo"], active="/tmp/myrepo")
    w = RepoListWidget(store)
    qtbot.addWidget(w)
    w.set_active_worktrees(
        [
            Worktree(
                path="/tmp/myrepo",
                branch="master",
                head_sha="x",
                is_locked=False,
                lock_reason=None,
                is_bare=False,
                is_main=True,
            ),
            _wt("/tmp/myrepo-feat", branch="feat"),
        ]
    )
    w.reload()
    model = w._model
    open_header = None
    for row in range(model.rowCount()):
        item = model.item(row)
        if item.data(_KIND_ROLE) is _RowKind.OPEN_HEADER:
            open_header = item
            break
    assert open_header is not None
    repo_item = open_header.child(0)
    assert repo_item.rowCount() == 1
    wt_child = repo_item.child(0)
    assert wt_child.data(Qt.UserRole) == "/tmp/myrepo-feat"
    assert wt_child.data(_KIND_ROLE) is _RowKind.WORKTREE


def test_inactive_repos_do_not_show_worktree_children(qtbot):
    store = _FakeStore(open_=["/tmp/myrepo", "/tmp/other"], active="/tmp/myrepo")
    w = RepoListWidget(store)
    qtbot.addWidget(w)
    w.set_active_worktrees([_wt("/tmp/myrepo-feat")])
    w.reload()
    model = w._model
    open_header = next(
        model.item(r)
        for r in range(model.rowCount())
        if model.item(r).data(_KIND_ROLE) is _RowKind.OPEN_HEADER
    )
    other_item = open_header.child(1)
    assert other_item.rowCount() == 0


def test_clicking_worktree_child_emits_repo_switch_requested(qtbot):
    store = _FakeStore(open_=["/tmp/myrepo"], active="/tmp/myrepo")
    w = RepoListWidget(store)
    qtbot.addWidget(w)
    w.set_active_worktrees([_wt("/tmp/myrepo-feat")])
    w.reload()
    received: list[str] = []
    w.repo_switch_requested.connect(received.append)
    model = w._model
    open_header = next(
        model.item(r) for r in range(model.rowCount()) if model.item(r).text() == "OPEN"
    )
    repo_item = open_header.child(0)
    wt_child = repo_item.child(0)
    w._on_item_clicked(model.indexFromItem(wt_child))
    assert received == ["/tmp/myrepo-feat"]


# ── Active worktree stays visible + highlighted ────────────────────────────


def _main_wt(path, branch="master"):
    return Worktree(
        path=path,
        branch=branch,
        head_sha="x",
        is_locked=False,
        lock_reason=None,
        is_bare=False,
        is_main=True,
    )


def _open_header(model):
    for row in range(model.rowCount()):
        item = model.item(row)
        if item.data(_KIND_ROLE) is _RowKind.OPEN_HEADER:
            return item
    return None


def test_active_worktree_stays_visible_under_parent(qtbot):
    """Clicking a worktree makes it active; it must remain shown as a child of
    its owning open repo rather than vanishing from the list."""
    # Group loaded while the main repo was active, then the worktree was
    # clicked so the active path is now the worktree (not in open_repos).
    store = _FakeStore(open_=["/tmp/myrepo"], active="/tmp/myrepo-feat")
    w = RepoListWidget(store)
    qtbot.addWidget(w)
    w.set_active_worktrees(
        [_main_wt("/tmp/myrepo"), _wt("/tmp/myrepo-feat", branch="feat")],
        owner_path="/tmp/myrepo",
    )
    w.reload()

    open_header = _open_header(w._model)
    assert open_header is not None
    repo_item = open_header.child(0)
    assert repo_item.rowCount() == 1
    wt_child = repo_item.child(0)
    assert wt_child.data(Qt.UserRole) == "/tmp/myrepo-feat"


def test_active_worktree_child_is_highlighted_not_parent(qtbot):
    store = _FakeStore(open_=["/tmp/myrepo"], active="/tmp/myrepo-feat")
    w = RepoListWidget(store)
    qtbot.addWidget(w)
    w.set_active_worktrees(
        [_main_wt("/tmp/myrepo"), _wt("/tmp/myrepo-feat", branch="feat")],
        owner_path="/tmp/myrepo",
    )
    w.reload()

    repo_item = _open_header(w._model).child(0)
    wt_child = repo_item.child(0)
    # The clicked worktree is the active row; the parent repo is not.
    assert wt_child.data(_IS_ACTIVE_ROLE) is True
    assert repo_item.data(_IS_ACTIVE_ROLE) is not True


# ── A worktree with a row of its own is not listed under it ────────────────


def _worktree_children(w: RepoListWidget) -> list[str]:
    """The paths listed under the first open row."""
    repo_item = _open_header(w._model).child(0)
    return [repo_item.child(r).data(Qt.UserRole) for r in range(repo_item.rowCount())]


def _group_of(feat_path: str) -> list[Worktree]:
    return [
        _main_wt("/tmp/myrepo"),
        _wt(feat_path, branch="feat"),
        _wt("/tmp/myrepo-other", branch="other"),
    ]


def _list_with_open_row(qtbot, row: str, group: list[Worktree]) -> RepoListWidget:
    """A list whose only open row is the active repo *row*, owning *group*."""
    w = RepoListWidget(_FakeStore(open_=[row], active=row))
    qtbot.addWidget(w)
    w.set_active_worktrees(group, owner_path=row)
    w.reload()
    return w


_FOLDS_CASE = os.path.normcase("A") != "A"


@pytest.mark.parametrize(
    "row",
    [
        pytest.param("/tmp/myrepo-feat", id="spelled as git has it"),
        pytest.param("/tmp/myrepo-feat/", id="trailing separator"),
        pytest.param(
            "/TMP/MyRepo-Feat",
            id="letter case",
            marks=pytest.mark.skipif(not _FOLDS_CASE, reason="paths here differ by letter case"),
        ),
    ],
)
def test_a_linked_worktree_with_a_row_of_its_own_does_not_list_itself(qtbot, row):
    """Opened on its own row it owns the group, and the group holds it too:
    the row showed a child for the very folder it stands for, and clicking the
    child asked to switch to the repo already on screen."""
    w = _list_with_open_row(qtbot, row, _group_of("/tmp/myrepo-feat"))

    assert _worktree_children(w) == ["/tmp/myrepo-other"]


def test_a_main_repo_row_still_lists_every_linked_worktree(qtbot):
    w = _list_with_open_row(qtbot, "/tmp/myrepo", _group_of("/tmp/myrepo-feat"))

    assert _worktree_children(w) == ["/tmp/myrepo-feat", "/tmp/myrepo-other"]


def test_a_main_repo_row_opened_through_a_link_does_not_list_the_main_worktree(qtbot):
    """Git names the main worktree by its real path, which the row's text is not."""
    w = _list_with_open_row(qtbot, "/links/myrepo", _group_of("/tmp/myrepo-feat"))

    assert _worktree_children(w) == ["/tmp/myrepo-feat", "/tmp/myrepo-other"]


# ── Task 11: context menus ─────────────────────────────────────────────────


def test_context_menu_on_active_repo_has_add_and_manage(qtbot):
    store = _FakeStore(open_=["/tmp/myrepo"], active="/tmp/myrepo")
    w = RepoListWidget(store)
    qtbot.addWidget(w)
    w.set_active_worktrees([])
    w.reload()
    actions = w._build_context_actions_for_active_repo("/tmp/myrepo")
    labels = [a["label"] for a in actions]
    assert "Add Worktree…" in labels
    assert "Manage Worktrees…" in labels


def test_context_menu_on_worktree_row_has_open_lock_remove(qtbot):
    store = _FakeStore(open_=["/tmp/myrepo"], active="/tmp/myrepo")
    w = RepoListWidget(store)
    qtbot.addWidget(w)
    w.set_active_worktrees([_wt("/tmp/myrepo-feat", branch="feat")])
    w.reload()
    actions = w._build_context_actions_for_worktree("/tmp/myrepo-feat", locked=False)
    labels = [a["label"] for a in actions]
    assert "Open" in labels
    assert "Lock…" in labels
    assert "Remove…" in labels
    assert "Unlock" not in labels


def test_context_menu_on_locked_worktree_shows_unlock_not_lock(qtbot):
    store = _FakeStore(open_=["/tmp/myrepo"], active="/tmp/myrepo")
    w = RepoListWidget(store)
    qtbot.addWidget(w)
    w.reload()
    actions = w._build_context_actions_for_worktree("/tmp/locked", locked=True)
    labels = [a["label"] for a in actions]
    assert "Unlock" in labels
    assert "Lock…" not in labels


def test_worktree_action_signal_emits(qtbot):
    store = _FakeStore(open_=["/tmp/myrepo"], active="/tmp/myrepo")
    w = RepoListWidget(store)
    qtbot.addWidget(w)
    received: list = []
    w.worktree_action_requested.connect(lambda a, p: received.append((a, p)))
    w._emit_worktree_action("add", "/tmp/myrepo")
    w._emit_worktree_action("remove", "/tmp/myrepo-feat")
    assert received == [("add", "/tmp/myrepo"), ("remove", "/tmp/myrepo-feat")]
