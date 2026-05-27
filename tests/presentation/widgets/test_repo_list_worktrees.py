"""Worktree children rendering and context menus in RepoListWidget."""
from __future__ import annotations

from PySide6.QtCore import Qt

from git_gui.domain.entities import Worktree
from git_gui.presentation.widgets.repo_list import RepoListWidget


class _FakeStore:
    def __init__(self, open_=None, recent=None, active=None):
        self._open = list(open_ or [])
        self._recent = list(recent or [])
        self._active = active
    def load(self): pass
    def save(self): pass
    def get_open_repos(self): return list(self._open)
    def get_recent_repos(self): return list(self._recent)
    def get_active(self): return self._active
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
    def set_active(self, p): self._active = p
    def set_open_order(self, paths): self._open = list(paths)


def _wt(path, branch="feat", locked=False):
    return Worktree(
        path=path, branch=branch, head_sha="abc",
        is_locked=locked, lock_reason=None, is_bare=False, is_main=False,
    )


# ── Task 10: nesting ───────────────────────────────────────────────────────

def test_active_repo_worktrees_render_as_children(qtbot):
    store = _FakeStore(open_=["/tmp/myrepo"], active="/tmp/myrepo")
    w = RepoListWidget(store)
    qtbot.addWidget(w)
    w.set_active_worktrees([
        Worktree(path="/tmp/myrepo", branch="master", head_sha="x",
                 is_locked=False, lock_reason=None, is_bare=False, is_main=True),
        _wt("/tmp/myrepo-feat", branch="feat"),
    ])
    w.reload()
    model = w._model
    open_header = None
    for row in range(model.rowCount()):
        item = model.item(row)
        if item.data(Qt.UserRole + 1) == "header" and item.text() == "OPEN":
            open_header = item
            break
    assert open_header is not None
    repo_item = open_header.child(0)
    assert repo_item.rowCount() == 1
    wt_child = repo_item.child(0)
    assert wt_child.data(Qt.UserRole) == "/tmp/myrepo-feat"
    assert wt_child.data(Qt.UserRole + 1) == "worktree"


def test_inactive_repos_do_not_show_worktree_children(qtbot):
    store = _FakeStore(open_=["/tmp/myrepo", "/tmp/other"], active="/tmp/myrepo")
    w = RepoListWidget(store)
    qtbot.addWidget(w)
    w.set_active_worktrees([_wt("/tmp/myrepo-feat")])
    w.reload()
    model = w._model
    open_header = next(
        model.item(r) for r in range(model.rowCount())
        if model.item(r).data(Qt.UserRole + 1) == "header"
        and model.item(r).text() == "OPEN"
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
        model.item(r) for r in range(model.rowCount())
        if model.item(r).text() == "OPEN"
    )
    repo_item = open_header.child(0)
    wt_child = repo_item.child(0)
    w._on_item_clicked(model.indexFromItem(wt_child))
    assert received == ["/tmp/myrepo-feat"]


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
