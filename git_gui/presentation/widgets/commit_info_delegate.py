# git_gui/presentation/widgets/commit_info_delegate.py
from __future__ import annotations
from PySide6.QtCore import Qt, QRect, QSize
from PySide6.QtGui import QBrush, QColor, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem
from git_gui.presentation.widgets.ref_badge_delegate import _badge_color

SELECTION_COLOR = "#264f78"   # dark blue highlight for selected row
DIVIDER_COLOR = "#30363d"     # subtle separator between rows

BADGE_RADIUS = 4
BADGE_H_PAD = 4
BADGE_V_PAD = 2
BADGE_GAP = 4

MUTED_COLOR = "#8b949e"   # author, datetime, hash
CELL_PAD = 4              # horizontal padding inside cell


class CommitInfoDelegate(QStyledItemDelegate):
    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        fm = option.fontMetrics
        # 2 header rows + up to 3 message lines + padding
        return QSize(option.rect.width(), fm.height() * 5 + 24)

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

        # ── Sub-row 2: branch badges (left) + hash (right) ───────────────────
        r2_top = rect.top() + header_h
        r2 = QRect(rect.left() + CELL_PAD, r2_top, rect.width() - CELL_PAD * 2, header_h)
        cy2 = r2_top + header_h // 2
        badge_h = line_h + BADGE_V_PAD * 2
        x = rect.left() + CELL_PAD

        for name in info.branch_names:
            badge_w = fm.horizontalAdvance(name) + BADGE_H_PAD * 2
            badge_rect = QRect(x, cy2 - badge_h // 2, badge_w, badge_h)
            painter.setBrush(QBrush(_badge_color(name)))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(badge_rect, BADGE_RADIUS, BADGE_RADIUS)
            painter.setPen(QColor("white"))
            painter.drawText(badge_rect, Qt.AlignCenter, name)
            x += badge_w + BADGE_GAP

        # Hash right-aligned
        painter.setPen(QColor("white"))
        painter.drawText(r2, Qt.AlignVCenter | Qt.AlignRight, info.short_oid)

        # ── Message area: word-wrap, max 3 lines, elide with "..." ────────────
        msg_top = rect.top() + header_h * 2
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
