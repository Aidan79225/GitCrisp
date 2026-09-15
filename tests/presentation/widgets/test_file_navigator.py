"""Tests for FileNavigatorWidget."""

from __future__ import annotations

import pytest

from git_gui.domain.entities import FileStatus
from git_gui.presentation.models.diff_model import DiffModel
from git_gui.presentation.widgets.file_navigator import FileNavigatorWidget


@pytest.fixture
def files():
    return [
        FileStatus(path="a.py", status="staged", delta="modified"),
        FileStatus(path="b.py", status="staged", delta="added"),
        FileStatus(path="c.py", status="staged", delta="deleted"),
    ]


@pytest.fixture
def navigator(qtbot, files):
    model = DiffModel(files)
    widget = FileNavigatorWidget(model)
    qtbot.addWidget(widget)
    widget.show()
    return widget, model


def test_list_view_is_visible(navigator):
    widget, _ = navigator
    assert widget._list_view.isVisible()


def test_selection_model_is_list_views(navigator):
    widget, _ = navigator
    assert widget.selection_model is widget._list_view.selectionModel()


def test_currentChanged_signal_propagates_from_list_view(navigator, qtbot):
    widget, model = navigator
    received = []
    widget.currentChanged.connect(lambda cur, prev: received.append(cur.row()))

    idx = model.index(1)
    widget.selection_model.setCurrentIndex(idx, widget.selection_model.SelectionFlag.ClearAndSelect)

    assert received == [1]


def test_deselected_signal_propagates_from_list_view(navigator, qtbot):
    widget, model = navigator
    received = []
    widget.deselected.connect(lambda: received.append(True))

    widget._list_view.deselected.emit()

    assert received == [True]


# ── Height cap ─────────────────────────────────────────────────────────


def _make_files(n: int) -> list[FileStatus]:
    return [FileStatus(path=f"f{i}.py", status="staged", delta="modified") for i in range(n)]


def test_list_mode_sizehint_fits_few_rows(qtbot):
    """With fewer files than the cap, sizeHint reports just the rows needed."""
    model = DiffModel(_make_files(3))
    widget = FileNavigatorWidget(model)
    qtbot.addWidget(widget)
    widget.show()

    row_h = widget._list_view.sizeHintForRow(0)
    expected = 3 * row_h + 2 * widget._list_view.frameWidth()
    assert abs(widget.sizeHint().height() - expected) <= 2


def test_list_mode_sizehint_caps_at_eight_rows(qtbot):
    """With many files, sizeHint caps at exactly 8 rows."""
    model = DiffModel(_make_files(20))
    widget = FileNavigatorWidget(model)
    qtbot.addWidget(widget)
    widget.show()

    row_h = widget._list_view.sizeHintForRow(0)
    expected = 8 * row_h + 2 * widget._list_view.frameWidth()
    assert abs(widget.sizeHint().height() - expected) <= 2


def test_list_mode_sizehint_updates_after_model_reload(qtbot):
    """sizeHint must refresh when files are added — updateGeometry hook works."""
    model = DiffModel(_make_files(3))
    widget = FileNavigatorWidget(model)
    qtbot.addWidget(widget)
    widget.show()

    initial = widget.sizeHint().height()
    model.reload(_make_files(12))

    grown = widget.sizeHint().height()
    row_h = widget._list_view.sizeHintForRow(0)
    expected = 8 * row_h + 2 * widget._list_view.frameWidth()
    assert grown > initial
    assert abs(grown - expected) <= 2


def test_list_mode_horizontal_scrollbar_is_suppressed(qtbot):
    """The horizontal scrollbar would steal a row's worth of viewport height,
    so it must stay hidden when max_visible_rows is set. Without this, an
    8-row cap renders only 7 rows."""
    model = DiffModel(_make_files(20))
    widget = FileNavigatorWidget(model)
    qtbot.addWidget(widget)
    widget.resize(400, 600)
    widget.show()

    assert not widget._list_view.horizontalScrollBar().isVisible()
    row_h = widget._list_view.sizeHintForRow(0)
    assert widget._list_view.viewport().height() >= 8 * row_h


def test_list_mode_height_does_not_collapse_inside_scroll_area(qtbot):
    """Regression: QScrollArea(setWidgetResizable=True) sizes its widget via
    viewport.expandedTo(minimumSizeHint). When the navigator's minimumSizeHint
    was one row's worth, the parent layout shrank the navigator below its
    sizeHint, leaving only one row visible despite a 12-row model."""
    from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

    model = DiffModel(_make_files(12))
    nav = FileNavigatorWidget(model)
    content = QWidget()
    cl = QVBoxLayout(content)
    cl.setContentsMargins(0, 0, 0, 0)
    cl.addWidget(nav)
    cl.addStretch(1)
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setWidget(content)
    sa.resize(600, 400)
    qtbot.addWidget(sa)
    sa.show()
    qtbot.wait(20)

    assert nav.height() == nav.sizeHint().height()
    assert nav.minimumSizeHint().height() == nav.sizeHint().height()
