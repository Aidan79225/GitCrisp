from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPixmap

from git_gui.presentation.theme import get_theme_manager


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


def _relative_luminance(color: QColor) -> float:
    def linear(channel: float) -> float:
        if channel <= 0.03928:
            return channel / 12.92
        return ((channel + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * linear(color.redF())
        + 0.7152 * linear(color.greenF())
        + 0.0722 * linear(color.blueF())
    )


def _initials_color(fill: QColor) -> QColor:
    """Black or white, whichever has the higher WCAG contrast on *fill*.

    Lane colours run from pale yellow to deep blue, so no single text colour
    reads on all of them.
    """
    lum = _relative_luminance(fill)
    on_white = 1.05 / (lum + 0.05)
    on_black = (lum + 0.05) / 0.05
    return QColor(Qt.white) if on_white >= on_black else QColor(Qt.black)


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
        painter.setPen(_initials_color(fill))
        font = painter.font()
        font.setPixelSize(max(int(side * 0.45), 8))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, _initials(author))

    painter.restore()
