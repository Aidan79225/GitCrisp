"""The commit row delegate's graph column: how wide it may be, and how far it is scrolled.

The delegate is driven through its real paint() onto an image. A row's commit
info starts where its graph ends, so where the author text lands tells how wide
the delegate made the graph.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage, QPainter, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QStyleOptionViewItem

from git_gui.presentation.models.graph_model import INFO_ROLE, LANE_ROLE, CommitInfo, LaneData
from git_gui.presentation.widgets.commit_row_delegate import CELL_PAD, CommitRowDelegate
from git_gui.presentation.widgets.graph_lane_painter import LANE_W, row_graph_width

ROW_W = 40 * LANE_W
ROW_H = 4 * LANE_W
WIDE = LaneData(lane=0, color_idx=0, n_lanes=20, lines=[(19, 19, 1)])  # reaches lane 19
NARROW = LaneData(lane=0, color_idx=0, n_lanes=1)
INFO = CommitInfo(
    author="Alice",
    timestamp="2026-10-16",
    short_oid="bc8a15f6",
    branch_names=[],
    head_branch=None,
    message="Fix typo",
)


class _TextRecorder(QPainter):
    def __init__(self, device: QImage) -> None:
        super().__init__(device)
        self.rects: dict[str, QRect] = {}

    def drawText(self, rect, flags, text):
        self.rects[text] = QRect(rect)
        super().drawText(rect, flags, text)


def _row(lane_data: LaneData, info: CommitInfo | None = INFO):
    model = QStandardItemModel(1, 1)
    item = QStandardItem()
    item.setData(lane_data, LANE_ROLE)
    item.setData(info, INFO_ROLE)
    model.setItem(0, 0, item)
    return model.index(0, 0), model


def _paint(delegate: CommitRowDelegate, lane_data: LaneData, info=INFO) -> tuple[QImage, dict]:
    index, _model = _row(lane_data, info)
    image = QImage(ROW_W, ROW_H, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = _TextRecorder(image)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, ROW_W, ROW_H)
    delegate.paint(painter, option, index)
    painter.end()
    return image, painter.rects


def _info_left(delegate: CommitRowDelegate, lane_data: LaneData) -> int:
    _image, texts = _paint(delegate, lane_data)
    return texts["Alice"].left()


def test_without_a_limit_the_info_starts_where_the_rows_own_lanes_end(qtbot):
    assert _info_left(CommitRowDelegate(), WIDE) == row_graph_width(WIDE) + CELL_PAD


def test_a_graph_wider_than_the_limit_leaves_the_info_starting_at_the_limit(qtbot):
    delegate = CommitRowDelegate()
    delegate.set_graph_column(limit=6 * LANE_W, scroll=0)

    assert _info_left(delegate, WIDE) == 6 * LANE_W + CELL_PAD


def test_a_graph_narrower_than_the_limit_keeps_the_info_hugging_it(qtbot):
    delegate = CommitRowDelegate()
    delegate.set_graph_column(limit=6 * LANE_W, scroll=0)

    assert _info_left(delegate, NARROW) == row_graph_width(NARROW) + CELL_PAD


def test_lanes_scrolled_to_the_right_of_the_column_are_not_painted_over_the_info(qtbot):
    delegate = CommitRowDelegate()
    limit = 6 * LANE_W
    delegate.set_graph_column(limit=limit, scroll=0)
    # A graph-only row, so nothing but lanes can colour the pixels right of the column.
    image, _ = _paint(delegate, WIDE, info=None)

    reach = 19 * LANE_W + LANE_W // 2  # the lane-19 line, well past the column
    assert image.pixelColor(reach, ROW_H // 2).alpha() == 0
    assert all(image.pixelColor(x, ROW_H // 2).alpha() == 0 for x in range(limit, ROW_W))


def test_scrolling_brings_a_far_lane_into_the_column(qtbot):
    delegate = CommitRowDelegate()
    limit = 6 * LANE_W
    scroll = 15 * LANE_W
    delegate.set_graph_column(limit=limit, scroll=scroll)
    image, _ = _paint(delegate, WIDE, info=None)

    lane_19_at = 19 * LANE_W + LANE_W // 2 - scroll
    assert image.pixelColor(lane_19_at, ROW_H // 2).alpha() > 0


def test_a_row_with_no_lanes_still_has_no_graph_column(qtbot):
    delegate = CommitRowDelegate()
    delegate.set_graph_column(limit=6 * LANE_W, scroll=3 * LANE_W)
    index, _model = _row(NARROW)
    index.model().setData(index, None, LANE_ROLE)
    image = QImage(ROW_W, ROW_H, QImage.Format_ARGB32)
    painter = _TextRecorder(image)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, ROW_W, ROW_H)

    delegate.paint(painter, option, index)
    painter.end()

    assert painter.rects["Alice"].left() == CELL_PAD
