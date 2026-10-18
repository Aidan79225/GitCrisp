"""A drag-reorder the repo file cannot take is reported, and still shown.

The new order was saved inside the drop handler, and an OSError from the
write (a read-only repos.json, one held by antivirus or a sync client)
escaped it: the list on screen stayed in the old order and nothing told the
user the order would be lost on the next launch.
"""

from __future__ import annotations

from PySide6.QtCore import Qt

from git_gui.presentation.widgets.repo_list import RepoListWidget
from tests.presentation.test_repo_list_save_failure import _store_that_cannot_save


def _list_of_two_open_repos(qtbot, tmp_path) -> RepoListWidget:
    store = _store_that_cannot_save(tmp_path)
    store.add_open("/repo/b")
    store.add_open("/repo/a")
    w = RepoListWidget(store)
    qtbot.addWidget(w)
    w.reload()
    return w


def _open_rows(w: RepoListWidget) -> list[str]:
    header = w._model.item(0)
    return [header.child(r).data(Qt.UserRole) for r in range(header.rowCount())]


def test_a_reorder_the_repo_file_cannot_take_is_reported(qtbot, tmp_path):
    w = _list_of_two_open_repos(qtbot, tmp_path)

    with qtbot.waitSignal(w.save_failed, timeout=1000):
        w._tree.repo_reorder_requested.emit("/repo/b", 0)


def test_a_reorder_the_repo_file_cannot_take_still_shows_the_new_order(qtbot, tmp_path):
    w = _list_of_two_open_repos(qtbot, tmp_path)

    w._tree.repo_reorder_requested.emit("/repo/b", 0)

    assert _open_rows(w) == ["/repo/b", "/repo/a"]
