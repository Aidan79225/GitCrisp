# git_gui/presentation/widgets/commit_info_delegate.py
from __future__ import annotations
from PySide6.QtCore import Qt, QRect, QSize
from PySide6.QtGui import QBrush, QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem
from git_gui.presentation.widgets.ref_badge_delegate import _badge_color, _badge_display_name

SELECTION_COLOR = "#264f78"   # dark blue highlight for selected row
DIVIDER_COLOR = "#30363d"     # subtle separator between rows

BADGE_RADIUS = 4
BADGE_H_PAD = 4
BADGE_V_PAD = 2
BADGE_GAP = 4

MUTED_COLOR = "#8b949e"   # author, datetime, hash
CELL_PAD = 4              # horizontal padding inside cell


def _badge_line_count(fm: QFontMetrics, branch_names: list[str],
                      first_line_width: int, full_width: int) -> int:
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


class CommitInfoDelegate(QStyledItemDelegate):
    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        from git_gui.presentation.models.graph_model import CommitInfo
        fm = option.fontMetrics
        line_h = fm.height()
        header_h = line_h + 8

        info: CommitInfo | None = index.data(Qt.UserRole + 1)
        if info is None:
            return QSize(option.rect.width(), header_h * 2 + line_h * 3 + 8)

        cell_w = option.rect.width() - CELL_PAD * 2 if option.rect.width() > 0 else 400
        hash_w = fm.horizontalAdvance(info.short_oid) + BADGE_GAP * 2
        first_line_w = cell_w - hash_w
        badge_lines = _badge_line_count(fm, info.branch_names, first_line_w, cell_w)

        # author row + badge rows + 3 message lines + padding
        return QSize(option.rect.width(), header_h * (1 + badge_lines) + line_h * 3 + 8)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        from git_gui.presentation.models.graph_model import CommitInfo
        info: CommitInfo | None = index.data(Qt.UserRole + 1)
        if info is None:
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        rect = option.rect

        # ── Selection highlight ───────────────────────────────────────────────
        if option.state & QStyle.State_Selected:
            painter.fillRect(rect, QColor(SELECTION_COLOR))

        fm = painter.fontMetrics()
        line_h = fm.height()
        header_h = line_h + 8  # single-line row height (text + padding)

        # ── Sub-row 1: author (left) + datetime (right) ──────────────────────
        r1 = QRect(rect.left() + CELL_PAD, rect.top(), rect.width() - CELL_PAD * 2, header_h)
        # Strip email from author: "Alice <a@a.com>" → "Alice"
        author_name = info.author.split("<")[0].strip() if "<" in info.author else info.author
        painter.setPen(QColor("white"))
        painter.drawText(r1, Qt.AlignVCenter | Qt.AlignLeft, author_name)
        painter.setPen(QColor(MUTED_COLOR))
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
            painter.setPen(QColor("white"))
            painter.drawText(badge_rect, Qt.AlignCenter, display)
            x += badge_w + BADGE_GAP

        # Hash right-aligned on first badge line
        r2_first = QRect(rect.left() + CELL_PAD, r2_top, cell_w, header_h)
        painter.setPen(QColor("white"))
        painter.drawText(r2_first, Qt.AlignVCenter | Qt.AlignRight, info.short_oid)

        # Total badge lines for message offset
        badge_lines = _badge_line_count(fm, info.branch_names, first_line_max_x, cell_w)

        # ── Message area: word-wrap, max 3 lines, elide with "..." ────────────
        msg_top = rect.top() + header_h * (1 + badge_lines)
        msg_w = rect.width() - CELL_PAD * 2
        msg_h = rect.bottom() - msg_top
        r3 = QRect(rect.left() + CELL_PAD, msg_top, msg_w, msg_h)
        painter.setPen(QColor(MUTED_COLOR))

        max_lines = 3
        words = info.message.split()
        lines: list[str] = []
        current = ""
        for word in words:
            trial = f"{current} {word}".strip()
            if fm.horizontalAdvance(trial) > msg_w and current:
                lines.append(current)
                current = word
                if len(lines) == max_lines:
                    break
            else:
                current = trial
        if current and len(lines) < max_lines:
            lines.append(current)

        # If text was truncated, add "..." to last line
        if " ".join(lines) != info.message and lines:
            last = lines[-1]
            ellipsis = last + "..."
            while fm.horizontalAdvance(ellipsis) > msg_w and len(last) > 0:
                last = last[:-1]
                ellipsis = last + "..."
            lines[-1] = ellipsis

        for i, line in enumerate(lines):
            ly = msg_top + i * line_h
            line_rect = QRect(rect.left() + CELL_PAD, ly, msg_w, line_h)
            painter.drawText(line_rect, Qt.AlignVCenter | Qt.AlignLeft, line)

        # ── Bottom divider ────────────────────────────────────────────────────
        painter.setPen(QColor(DIVIDER_COLOR))
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

        painter.restore()
