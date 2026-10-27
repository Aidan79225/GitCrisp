from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPixmap

from git_gui.presentation.theme import get_theme_manager
from git_gui.presentation.theme.contrast import readable_text_on


def _initials(author: str) -> str:
    name = author.split("<")[0].strip() if "<" in author else author.strip()
    parts = name.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    if parts:
        return parts[0][0].upper()
    return "?"


def _color_for_author(author: str) -> QColor:
    """A stable colour per author, from the palette the graph lanes use.

    The blame gutter draws from the same palette, so the app keeps one colour
    vocabulary for identity, and a theme restyles avatars along with lanes.
    """
    colors = get_theme_manager().current.colors.graph_lane_colors
    h = 0
    for ch in author:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return QColor(colors[h % len(colors)])


def paint_avatar(
    painter: QPainter,
    rect: QRect,
    author: str,
    pixmap: QPixmap | None = None,
) -> None:
    """Paint a circular avatar inside *rect* (should be square).

    If *pixmap* is provided and non-null, render it as the circle's fill
    (scaled to size). Otherwise render deterministic-color initials.
    """
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)

    side = min(rect.width(), rect.height())
    cx = rect.x() + rect.width() / 2.0
    cy = rect.y() + rect.height() / 2.0
    # Inset by 0.5px so antialiased edges aren't clipped by the rect.
    circle = QRectF(cx - side / 2.0 + 0.5, cy - side / 2.0 + 0.5, side - 1.0, side - 1.0)

    painter.setPen(Qt.NoPen)
    if pixmap is not None and not pixmap.isNull():
        scaled = pixmap.scaled(
            int(circle.width()),
            int(circle.height()),
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        brush = QBrush(scaled)
        # Position the pattern so it lines up with our ellipse, not (0,0).
        from PySide6.QtGui import QTransform

        brush.setTransform(QTransform().translate(circle.x(), circle.y()))
        painter.setBrush(brush)
        painter.drawEllipse(circle)
    else:
        fill = _color_for_author(author)
        painter.setBrush(fill)
        painter.drawEllipse(circle)
        painter.setPen(readable_text_on(fill))
        font = painter.font()
        font.setPixelSize(max(int(side * 0.45), 8))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, _initials(author))

    painter.restore()
