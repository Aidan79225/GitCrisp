"""Mouse interaction with the repository list: dragging, clicking, painting."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QImage, QMouseEvent, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem

from git_gui.presentation.widgets.repo_list import RepoListWidget
from tests.presentation.widgets.test_repo_list_worktrees import _FakeStore, _wt

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


# ── Painting ────────────────────────────────────────────────────────────────
class _TextRecorder(QPainter):
    def __init__(self, device) -> None:
        super().__init__(device)
        self.texts: list[str] = []

    def drawText(self, *args) -> None:
        self.texts.append(args[-1])
        super().drawText(*args)


def _painted_lines(w: RepoListWidget, item) -> list[str]:
    index = w._model.indexFromItem(item)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 320, 40)
    option.font = w.font()
    image = QImage(320, 40, QImage.Format_ARGB32)
    painter = _TextRecorder(image)
    w._tree.itemDelegate().paint(painter, option, index)
    painter.end()
    return painter.texts


def _worktree_row(w: RepoListWidget, path: str, branch: str | None):
    w.set_active_worktrees([_wt(path, branch=branch)], owner_path="C:/a/one")
    w.reload()
    owner = w._model.itemFromIndex(_open_row_index(w, "C:/a/one"))
    return owner.child(0)


def test_a_worktree_row_names_its_branch(qtbot):
    w = _shown_list(qtbot, _FakeStore(open_=["C:/a/one"], active="C:/a/one"))

    lines = _painted_lines(w, _worktree_row(w, "C:/wt/review", "feature/login"))

    assert lines == ["feature/login", "C:/wt/review"]


def test_a_detached_worktree_row_says_so(qtbot):
    w = _shown_list(qtbot, _FakeStore(open_=["C:/a/one"], active="C:/a/one"))

    lines = _painted_lines(w, _worktree_row(w, "C:/wt/tmp", None))

    assert lines == ["(detached)", "C:/wt/tmp"]


def test_a_repo_row_names_its_folder(qtbot):
    w = _shown_list(qtbot, _FakeStore(open_=["C:/a/one"], active="C:/a/one"))
    row = w._model.itemFromIndex(_open_row_index(w, "C:/a/one"))

    assert _painted_lines(w, row) == ["one", "C:/a/one"]


# ── Clicking ────────────────────────────────────────────────────────────────
def _switches_after_clicking(w: RepoListWidget, index) -> list[str]:
    switched: list[str] = []
    w.repo_switch_requested.connect(switched.append)
    w._tree.clicked.emit(index)
    return switched


def test_clicking_the_active_repo_does_not_reopen_it(qtbot):
    w = _shown_list(qtbot, _FakeStore(open_=_OPEN, active="C:/a/one"))

    assert _switches_after_clicking(w, _open_row_index(w, "C:/a/one")) == []


def test_clicking_another_open_repo_switches_to_it(qtbot):
    w = _shown_list(qtbot, _FakeStore(open_=_OPEN, active="C:/a/one"))

    assert _switches_after_clicking(w, _open_row_index(w, "C:/a/two")) == ["C:/a/two"]


def test_clicking_the_active_worktree_does_not_reopen_it(qtbot):
    w = _shown_list(qtbot, _FakeStore(open_=["C:/a/one"], active="C:/wt/review"))
    row = _worktree_row(w, "C:/wt/review", "feature/login")

    assert _switches_after_clicking(w, w._model.indexFromItem(row)) == []


# ── Dragging from outside a row ─────────────────────────────────────────────
def test_a_drag_from_blank_space_does_not_carry_the_last_clicked_repo(qtbot, monkeypatch):
    w = _shown_list(qtbot, _FakeStore(open_=_OPEN, active="C:/a/one"))
    dragged: list[str] = []
    monkeypatch.setattr(w._tree, "startDrag", lambda _actions: dragged.append("drag"))
    viewport = w._tree.viewport()
    QTest.mouseClick(
        viewport,
        Qt.LeftButton,
        Qt.NoModifier,
        w._tree.visualRect(_open_row_index(w, "C:/a/one")).center(),
    )
    blank = QPoint(viewport.width() // 2, viewport.height() - 10)
    assert not w._tree.indexAt(blank).isValid()

    _press_and_drag(w, blank, -(QApplication.startDragDistance() + 40))

    assert dragged == []


# ── Dropping on a section header ────────────────────────────────────────────
def _header_index(w: RepoListWidget, title: str):
    model = w._model
    return next(model.index(r, 0) for r in range(model.rowCount()) if model.item(r).text() == title)


def _reorders_after_dropping(w: RepoListWidget, index, path: str) -> list[tuple[str, int]]:
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QDropEvent

    mime = QMimeData()
    mime.setText(path)
    pos = QPointF(w._tree.visualRect(index).center())
    reordered: list[tuple[str, int]] = []
    w._tree.repo_reorder_requested.connect(lambda p, row: reordered.append((p, row)))
    w._tree.dropEvent(QDropEvent(pos, Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier))
    return reordered


def test_dropping_a_repo_on_the_open_header_moves_it_to_the_top(qtbot):
    w = _shown_list(qtbot, _FakeStore(open_=_OPEN, recent=["C:/b/old"], active="C:/a/one"))

    assert _reorders_after_dropping(w, _header_index(w, "OPEN"), "C:/a/three") == [
        ("C:/a/three", 0)
    ]


def test_dropping_a_repo_on_the_recent_header_leaves_the_order_alone(qtbot):
    w = _shown_list(qtbot, _FakeStore(open_=_OPEN, recent=["C:/b/old"], active="C:/a/one"))

    assert _reorders_after_dropping(w, _header_index(w, "RECENT"), "C:/a/three") == []
