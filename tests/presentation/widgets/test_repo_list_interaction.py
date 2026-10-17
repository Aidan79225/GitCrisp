"""Mouse interaction with the repository list: dragging, clicking, painting."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from git_gui.presentation.widgets.repo_list import RepoListWidget
from tests.presentation.widgets.test_repo_list_worktrees import _FakeStore

_OPEN = ["C:/a/one", "C:/a/two", "C:/a/three"]


def _shown_list(qtbot, store) -> RepoListWidget:
    w = RepoListWidget(store)
    qtbot.addWidget(w)
    w.resize(320, 480)
    w.reload()
    w.show()
    qtbot.waitExposed(w)
    return w


def _open_row_index(w: RepoListWidget, path: str):
    model = w._model
    header = next(model.item(r) for r in range(model.rowCount()) if model.item(r).text() == "OPEN")
    for r in range(header.rowCount()):
        if header.child(r).data(Qt.UserRole) == path:
            return model.indexFromItem(header.child(r))
    raise AssertionError(f"no OPEN row for {path}")


def _press_and_drag(w: RepoListWidget, start: QPoint, distance: int) -> None:
    viewport = w._tree.viewport()
    QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, start)
    end = start + QPoint(0, distance)
    move = QMouseEvent(
        QEvent.MouseMove,
        QPointF(end),
        QPointF(viewport.mapToGlobal(end)),
        Qt.NoButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    QApplication.sendEvent(viewport, move)


def test_dragging_an_open_repo_starts_a_reorder_drag(qtbot, monkeypatch):
    w = _shown_list(qtbot, _FakeStore(open_=_OPEN, active="C:/a/one"))
    dragged: list[str] = []
    monkeypatch.setattr(
        w._tree,
        "startDrag",
        lambda _actions: dragged.append(w._tree.currentIndex().data(Qt.UserRole)),
    )

    start = w._tree.visualRect(_open_row_index(w, "C:/a/three")).center()
    _press_and_drag(w, start, QApplication.startDragDistance() + 40)

    assert dragged == ["C:/a/three"]


def test_a_press_that_barely_moves_is_not_a_drag(qtbot, monkeypatch):
    w = _shown_list(qtbot, _FakeStore(open_=_OPEN, active="C:/a/one"))
    dragged: list[str] = []
    monkeypatch.setattr(w._tree, "startDrag", lambda _actions: dragged.append("drag"))

    start = w._tree.visualRect(_open_row_index(w, "C:/a/two")).center()
    _press_and_drag(w, start, 1)

    assert dragged == []
