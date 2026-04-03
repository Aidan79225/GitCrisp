# git_gui/presentation/widgets/ref_badge_delegate.py
from __future__ import annotations
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QBrush, QColor, QPainter
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem

BADGE_RADIUS = 4   # rounded corner radius
BADGE_H_PAD = 4    # horizontal padding inside badge
BADGE_V_PAD = 2    # vertical padding inside badge
BADGE_GAP = 4      # gap between consecutive badges, and after last badge

COLOR_HEAD = "#238636"    # green — HEAD / current branch
COLOR_REMOTE = "#1f4287"  # dark blue — remote-tracking branch (contains "/")
COLOR_LOCAL = "#0d6efd"   # blue — local branch


def _badge_color(name: str) -> QColor:
    # "HEAD -> branch" is the git decoration format for the current branch pointer
    if name == "HEAD" or name.startswith("HEAD ->"):
        return QColor(COLOR_HEAD)
    if "/" in name:
        return QColor(COLOR_REMOTE)
    return QColor(COLOR_LOCAL)


class RefBadgeDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        branch_names: list[str] = index.data(Qt.UserRole + 1) or []
        message: str = index.data(Qt.DisplayRole) or ""

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        rect = option.rect
        x = rect.left() + 2
        cy = rect.top() + rect.height() // 2
        fm = painter.fontMetrics()
        badge_h = fm.height() + BADGE_V_PAD * 2

        for name in branch_names:
            badge_w = fm.horizontalAdvance(name) + BADGE_H_PAD * 2
            badge_rect = QRect(x, cy - badge_h // 2, badge_w, badge_h)

            painter.setBrush(QBrush(_badge_color(name)))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(badge_rect, BADGE_RADIUS, BADGE_RADIUS)

            painter.setPen(QColor("white"))
            painter.drawText(badge_rect, Qt.AlignCenter, name)

            x += badge_w + BADGE_GAP

        # Draw commit message text after the badges
        text_rect = QRect(x, rect.top(), max(0, rect.right() - x), rect.height())
        painter.setPen(option.palette.text().color())
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, message)

        painter.restore()
