# git_gui/presentation/widgets/ref_badge_delegate.py
from __future__ import annotations
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QBrush, QColor, QPainter
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem
from git_gui.presentation.theme import get_theme_manager

BADGE_RADIUS = 4   # rounded corner radius
BADGE_H_PAD = 4    # horizontal padding inside badge
BADGE_V_PAD = 2    # vertical padding inside badge
BADGE_GAP = 4      # gap between consecutive badges, and after last badge

# TODO(theme): domain green for HEAD/current branch — no clean token yet
COLOR_HEAD = "#238636"


def _color_local() -> QColor:
    return get_theme_manager().current.colors.as_qcolor("ref_badge_branch_bg")


def _color_remote() -> QColor:
    return get_theme_manager().current.colors.as_qcolor("ref_badge_remote_bg")


def _color_tag() -> QColor:
    return get_theme_manager().current.colors.as_qcolor("ref_badge_tag_bg")


def _badge_color(name: str, head_branch: str | None = None) -> QColor:
    if name == "HEAD" or name.startswith("HEAD ->"):
        return QColor(COLOR_HEAD)
    if head_branch and name == head_branch:
        return QColor(COLOR_HEAD)
    if name.startswith("tag:"):
        return _color_tag()
    if "/" in name:
        return _color_remote()
    return _color_local()


def _badge_display_name(name: str) -> str:
    """Strip 'tag:' prefix for display."""
    if name.startswith("tag:"):
        return name[4:]
    return name


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
            display = _badge_display_name(name)
            badge_w = fm.horizontalAdvance(display) + BADGE_H_PAD * 2
            badge_rect = QRect(x, cy - badge_h // 2, badge_w, badge_h)

            painter.setBrush(QBrush(_badge_color(name)))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(badge_rect, BADGE_RADIUS, BADGE_RADIUS)

            painter.setPen(QColor("white"))  # TODO(theme): badge text color
            painter.drawText(badge_rect, Qt.AlignCenter, display)

            x += badge_w + BADGE_GAP

        # Draw commit message text after the badges
        text_rect = QRect(x, rect.top(), max(0, rect.right() - x), rect.height())
        painter.setPen(option.palette.text().color())
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, message)

        painter.restore()
