"""Delegate for a whole commit row: lane graph on the left, commit info right.

Both halves share one cell so the info can start at a per-row indent — just
clear of the lanes that row actually draws — instead of every row waiting on
the widest row in the history.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFontMetrics, QPainter, QTextLayout, QTextOption
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from git_gui.presentation.models.graph_model import INFO_ROLE, LANE_ROLE, CommitInfo
from git_gui.presentation.theme import ColorRole, get_theme_manager
from git_gui.presentation.widgets.graph_lane_painter import paint_lanes, row_graph_width
from git_gui.presentation.widgets.ref_badge_delegate import _badge_color, _badge_display_name


def _selection_color() -> QColor:
    return get_theme_manager().current.colors.as_qcolor(ColorRole.PRIMARY)


def _divider_color() -> QColor:
    return get_theme_manager().current.colors.as_qcolor(ColorRole.OUTLINE)


def _muted_color() -> QColor:
    return get_theme_manager().current.colors.as_qcolor(ColorRole.ON_SURFACE_VARIANT)


BADGE_RADIUS = 4
BADGE_H_PAD = 4
BADGE_V_PAD = 2
BADGE_GAP = 4

CELL_PAD = 4  # horizontal padding inside cell

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


def _badge_line_count(
    fm: QFontMetrics, branch_names: list[str], first_line_width: int, full_width: int
) -> int:
    """Compute how many lines badges need, given first-line and subsequent-line widths."""
    if not branch_names:
        return 1
    lines = 1
    x = 0
    max_x = first_line_width
    for name in branch_names:
        display = _badge_display_name(name)
        badge_w = fm.horizontalAdvance(display) + BADGE_H_PAD * 2
        if x > 0 and x + badge_w > max_x:
            lines += 1
            x = 0
            max_x = full_width
        x += badge_w + BADGE_GAP
    return lines


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
        hash_w = fm.horizontalAdvance(info.short_oid) + BADGE_GAP * 2
        first_line_w = cell_w - hash_w
        badge_lines = _badge_line_count(fm, info.branch_names, first_line_w, cell_w)

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
        r1 = QRect(rect.left() + CELL_PAD, rect.top(), rect.width() - CELL_PAD * 2, header_h)
        # Strip email from author: "Alice <a@a.com>" → "Alice"
        author_name = info.author.split("<")[0].strip() if "<" in info.author else info.author
        painter.setPen(get_theme_manager().current.colors.as_qcolor(ColorRole.ON_SURFACE))
        painter.drawText(r1, Qt.AlignVCenter | Qt.AlignLeft, author_name)
        painter.setPen(_muted_color())
        painter.drawText(r1, Qt.AlignVCenter | Qt.AlignRight, info.timestamp)

        # ── Sub-row 2+: branch badges (left, multi-line) + hash (right, first line) ─
        cell_w = rect.width() - CELL_PAD * 2
        hash_w = fm.horizontalAdvance(info.short_oid) + BADGE_GAP * 2
        first_line_max_x = cell_w - hash_w
        badge_h = line_h + BADGE_V_PAD * 2

        badge_line = 0
        r2_top = rect.top() + header_h
        x = 0

        for name in info.branch_names:
            display = _badge_display_name(name)
            badge_w = fm.horizontalAdvance(display) + BADGE_H_PAD * 2
            max_x = first_line_max_x if badge_line == 0 else cell_w
            if x > 0 and x + badge_w > max_x:
                badge_line += 1
                x = 0
            row_top = r2_top + badge_line * header_h
            cy = row_top + header_h // 2
            bx = rect.left() + CELL_PAD + x
            badge_rect = QRect(bx, cy - badge_h // 2, badge_w, badge_h)
            painter.setBrush(QBrush(_badge_color(name, info.head_branch)))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(badge_rect, BADGE_RADIUS, BADGE_RADIUS)
            painter.setPen(get_theme_manager().current.colors.as_qcolor(ColorRole.ON_BADGE))
            painter.drawText(badge_rect, Qt.AlignCenter, display)
            x += badge_w + BADGE_GAP

        # Hash right-aligned on first badge line
        r2_first = QRect(rect.left() + CELL_PAD, r2_top, cell_w, header_h)
        painter.setPen(get_theme_manager().current.colors.as_qcolor(ColorRole.ON_SURFACE))
        painter.drawText(r2_first, Qt.AlignVCenter | Qt.AlignRight, info.short_oid)

        # Total badge lines for message offset
        badge_lines = _badge_line_count(fm, info.branch_names, first_line_max_x, cell_w)

        msg_top = rect.top() + header_h * (1 + badge_lines)
        first_message_line = QRect(rect.left() + CELL_PAD, msg_top, cell_w, line_h)
        self._paint_message(painter, info.message, first_message_line)

        self._paint_divider(painter, row_rect)
        painter.restore()

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
