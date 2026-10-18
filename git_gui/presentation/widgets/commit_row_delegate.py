"""Delegate for a whole commit row: lane graph on the left, commit info right.

Both halves share one cell so the info can start at a per-row indent — just
clear of the lanes that row actually draws — instead of every row waiting on
the widest row in the history.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QTextLayout, QTextOption
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from git_gui.presentation.models.graph_model import INFO_ROLE, LANE_ROLE, CommitInfo
from git_gui.presentation.theme import ColorRole, get_theme_manager
from git_gui.presentation.widgets.graph_lane_painter import paint_lanes, row_graph_width
from git_gui.presentation.widgets.ref_badge_delegate import (
    BADGE_GAP,
    BADGE_H_PAD,
    BADGE_V_PAD,
    _badge_color,
    _badge_display_name,
    paint_badge,
)


def _selection_color() -> QColor:
    return get_theme_manager().current.colors.as_qcolor(ColorRole.PRIMARY)


def _divider_color() -> QColor:
    return get_theme_manager().current.colors.as_qcolor(ColorRole.OUTLINE)


def _muted_color() -> QColor:
    return get_theme_manager().current.colors.as_qcolor(ColorRole.ON_SURFACE_VARIANT)


CELL_PAD = 4  # horizontal padding inside cell
AUTHOR_DATE_GAP = 8  # least space between the author and the date

MESSAGE_LINES = 3  # lines every row reserves for the commit subject


def _message_line_spans(painter: QPainter, message: str, width: int) -> list[tuple[int, int]]:
    """Where each of the first MESSAGE_LINES wrapped lines starts and ends.

    Positions count UTF-16 units, as Qt does. A line breaks between words where
    it can and inside one where it must: CJK text has no spaces to break at.
    """
    layout = QTextLayout(message, painter.font(), painter.device())
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    layout.beginLayout()
    spans: list[tuple[int, int]] = []
    while len(spans) < MESSAGE_LINES:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(width)
        spans.append((line.textStart(), line.textStart() + line.textLength()))
    layout.endLayout()
    return spans


def _wrap_message(painter: QPainter, message: str, width: int) -> list[str]:
    """The message as at most MESSAGE_LINES lines, the last elided if text is left over."""
    spans = _message_line_spans(painter, message, width)
    # Qt's positions count an emoji as two units; slicing the str directly drifts.
    units = message.encode("utf-16-le")
    lines = [units[start * 2 : end * 2].decode("utf-16-le") for start, end in spans]
    last_start, last_end = spans[-1]
    if last_end * 2 < len(units):
        rest = units[last_start * 2 :].decode("utf-16-le")
        lines[-1] = painter.fontMetrics().elidedText(rest, Qt.ElideRight, width)
    return lines


@dataclass(frozen=True)
class _PlacedBadge:
    name: str
    label: str
    line: int
    x: int
    width: int


def _hash_width(fm: QFontMetrics, short_oid: str) -> int:
    """Room the sha takes at the right of the first badge line, gap included."""
    return fm.horizontalAdvance(short_oid) + BADGE_GAP * 2


def _layout_badges(
    fm: QFontMetrics, branch_names: list[str], first_line_width: int, full_width: int
) -> list[_PlacedBadge]:
    """Flow the badges left to right, wrapping onto lines of ``full_width``.

    A badge too wide even for a line to itself has its label elided to fit, so
    it never runs under the sha or past the edge of the row.
    """
    placed: list[_PlacedBadge] = []
    line = 0
    x = 0
    line_width = first_line_width
    for name in branch_names:
        label = _badge_display_name(name)
        width = fm.horizontalAdvance(label) + BADGE_H_PAD * 2
        if x > 0 and x + width > line_width:
            line += 1
            x = 0
            line_width = full_width
        if width > line_width - x:
            width = line_width - x
            label = fm.elidedText(label, Qt.ElideRight, width - BADGE_H_PAD * 2)
        placed.append(_PlacedBadge(name, label, line, x, width))
        x += width + BADGE_GAP
    return placed


def _badge_line_count(placed: list[_PlacedBadge]) -> int:
    return placed[-1].line + 1 if placed else 1


class CommitRowDelegate(QStyledItemDelegate):
    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        fm = option.fontMetrics
        line_h = fm.height()
        header_h = line_h + 8

        info: CommitInfo | None = index.data(INFO_ROLE)
        if info is None:
            return QSize(option.rect.width(), header_h * 2 + line_h * MESSAGE_LINES + 8)

        indent = row_graph_width(index.data(LANE_ROLE))
        row_w = option.rect.width() if option.rect.width() > 0 else indent + 400
        cell_w = max(row_w - indent - CELL_PAD * 2, 1)
        first_line_w = cell_w - _hash_width(fm, info.short_oid)
        badge_lines = _badge_line_count(_layout_badges(fm, info.branch_names, first_line_w, cell_w))

        # author row + badge rows + message lines + padding
        return QSize(option.rect.width(), header_h * (1 + badge_lines) + line_h * MESSAGE_LINES + 8)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        info: CommitInfo | None = index.data(INFO_ROLE)
        lane_data = index.data(LANE_ROLE)
        if info is None and lane_data is None:
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        row_rect = option.rect
        selected = bool(option.state & QStyle.State_Selected)

        # ── Selection highlight (whole row, drawn under both halves) ──────────
        if selected:
            painter.fillRect(row_rect, _selection_color())

        # ── Lane graph, then the commit info clear of it ──────────────────────
        indent = row_graph_width(lane_data)
        if lane_data is not None:
            graph_rect = QRect(row_rect.left(), row_rect.top(), indent, row_rect.height())
            paint_lanes(painter, graph_rect, lane_data, selected=selected)

        rect = QRect(
            row_rect.left() + indent,
            row_rect.top(),
            max(row_rect.width() - indent, 1),
            row_rect.height(),
        )
        if info is None:
            self._paint_divider(painter, row_rect)
            painter.restore()
            return

        fm = painter.fontMetrics()
        line_h = fm.height()
        header_h = line_h + 8  # single-line row height (text + padding)

        # ── Sub-row 1: author (left) + datetime (right) ──────────────────────
        cell_w = rect.width() - CELL_PAD * 2
        header = QRect(rect.left() + CELL_PAD, rect.top(), cell_w, header_h)
        self._paint_author_and_date(painter, info, header)

        # ── Sub-row 2+: branch badges (left, multi-line) + hash (right, first line) ─
        first_ref_line = QRect(rect.left() + CELL_PAD, rect.top() + header_h, cell_w, header_h)
        badge_lines = self._paint_refs(painter, info, first_ref_line)

        msg_top = rect.top() + header_h * (1 + badge_lines)
        first_message_line = QRect(rect.left() + CELL_PAD, msg_top, cell_w, line_h)
        self._paint_message(painter, info.message, first_message_line)

        self._paint_divider(painter, row_rect)
        painter.restore()

    @staticmethod
    def _paint_author_and_date(painter: QPainter, info: CommitInfo, line: QRect) -> None:
        """The date at the right, and the author left of it, elided short of the date."""
        fm = painter.fontMetrics()
        # Strip email from author: "Alice <a@a.com>" → "Alice"
        author_name = info.author.split("<")[0].strip() if "<" in info.author else info.author
        author_room = line.width() - fm.horizontalAdvance(info.timestamp) - AUTHOR_DATE_GAP
        author = fm.elidedText(author_name, Qt.ElideRight, author_room)
        painter.setPen(get_theme_manager().current.colors.as_qcolor(ColorRole.ON_SURFACE))
        painter.drawText(line, Qt.AlignVCenter | Qt.AlignLeft, author)
        painter.setPen(_muted_color())
        painter.drawText(line, Qt.AlignVCenter | Qt.AlignRight, info.timestamp)

    @staticmethod
    def _paint_refs(painter: QPainter, info: CommitInfo, first_line: QRect) -> int:
        """Paint the badges and the sha, and return how many lines the badges took."""
        fm = painter.fontMetrics()
        first_line_w = first_line.width() - _hash_width(fm, info.short_oid)
        placed = _layout_badges(fm, info.branch_names, first_line_w, first_line.width())
        badge_h = fm.height() + BADGE_V_PAD * 2
        for badge in placed:
            if not badge.label:
                continue  # not even room for an ellipsis
            cy = first_line.top() + badge.line * first_line.height() + first_line.height() // 2
            rect = QRect(first_line.left() + badge.x, cy - badge_h // 2, badge.width, badge_h)
            color = _badge_color(badge.name, info.head_branch, info.remote_branches)
            paint_badge(painter, rect, color, badge.label)

        painter.setPen(get_theme_manager().current.colors.as_qcolor(ColorRole.ON_SURFACE))
        painter.drawText(first_line, Qt.AlignVCenter | Qt.AlignRight, info.short_oid)
        return _badge_line_count(placed)

    @staticmethod
    def _paint_message(painter: QPainter, message: str, first_line: QRect) -> None:
        painter.setPen(_muted_color())
        for i, line in enumerate(_wrap_message(painter, message, first_line.width())):
            line_rect = first_line.translated(0, i * first_line.height())
            painter.drawText(line_rect, Qt.AlignVCenter | Qt.AlignLeft, line)

    @staticmethod
    def _paint_divider(painter: QPainter, row_rect: QRect) -> None:
        painter.setPen(_divider_color())
        painter.drawLine(row_rect.left(), row_rect.bottom(), row_rect.right(), row_rect.bottom())
