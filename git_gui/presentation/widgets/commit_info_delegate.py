# git_gui/presentation/widgets/commit_info_delegate.py
from __future__ import annotations
from PySide6.QtCore import Qt, QRect, QSize
from PySide6.QtGui import QBrush, QColor, QPainter
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem
from git_gui.presentation.widgets.ref_badge_delegate import _badge_color

BADGE_RADIUS = 4
BADGE_H_PAD = 4
BADGE_V_PAD = 2
BADGE_GAP = 4

MUTED_COLOR = "#8b949e"   # author, datetime, hash
CELL_PAD = 4              # horizontal padding inside cell


class CommitInfoDelegate(QStyledItemDelegate):
    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        fm = option.fontMetrics
        return QSize(option.rect.width(), fm.height() * 3 + 12)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        from git_gui.presentation.models.graph_model import CommitInfo
        info: CommitInfo | None = index.data(Qt.UserRole + 1)
        if info is None:
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        rect = option.rect
        sub_h = rect.height() // 3
        fm = painter.fontMetrics()

        # ── Sub-row 1: author (left) + datetime (right) ──────────────────────
        r1 = QRect(rect.left() + CELL_PAD, rect.top(), rect.width() - CELL_PAD * 2, sub_h)
        painter.setPen(QColor(MUTED_COLOR))
        painter.drawText(r1, Qt.AlignVCenter | Qt.AlignLeft, info.author)
        painter.drawText(r1, Qt.AlignVCenter | Qt.AlignRight, info.timestamp)

        # ── Sub-row 2: branch badges (left) + hash (right) ───────────────────
        r2_top = rect.top() + sub_h
        r2 = QRect(rect.left() + CELL_PAD, r2_top, rect.width() - CELL_PAD * 2, sub_h)
        cy2 = r2_top + sub_h // 2
        badge_h = fm.height() + BADGE_V_PAD * 2
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
        painter.setPen(QColor(MUTED_COLOR))
        painter.drawText(r2, Qt.AlignVCenter | Qt.AlignRight, info.short_oid)

        # ── Sub-row 3: commit message ─────────────────────────────────────────
        r3 = QRect(rect.left() + CELL_PAD, rect.top() + sub_h * 2,
                   rect.width() - CELL_PAD * 2, sub_h)
        painter.setPen(option.palette.text().color())
        painter.drawText(r3, Qt.AlignVCenter | Qt.AlignLeft, info.message)

        painter.restore()
