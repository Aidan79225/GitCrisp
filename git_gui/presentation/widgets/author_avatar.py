# git_gui/presentation/widgets/author_avatar.py
from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPixmap

_PALETTE = [
    "#e57373",
    "#f06292",
    "#ba68c8",
    "#9575cd",
    "#7986cb",
    "#64b5f6",
    "#4fc3f7",
    "#4dd0e1",
    "#4db6ac",
    "#81c784",
    "#aed581",
    "#dce775",
    "#ffd54f",
    "#ffb74d",
    "#ff8a65",
    "#a1887f",
]


def _initials(author: str) -> str:
    name = author.split("<")[0].strip() if "<" in author else author.strip()
    parts = name.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    if parts:
        return parts[0][0].upper()
    return "?"


def _color_for_author(author: str) -> QColor:
    h = 0
    for ch in author:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return QColor(_PALETTE[h % len(_PALETTE)])


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
        painter.setBrush(_color_for_author(author))
        painter.drawEllipse(circle)
        painter.setPen(QColor("#ffffff"))
        font = painter.font()
        font.setPixelSize(max(int(side * 0.45), 8))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, _initials(author))

    painter.restore()
