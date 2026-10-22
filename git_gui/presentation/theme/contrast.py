"""Which text colour reads on a theme colour: the one rule widgets share."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor


def readable_text_on(fill: QColor) -> QColor:
    """Black or white, whichever has the higher WCAG contrast on *fill*.

    Theme colours run from pale yellow to deep blue, so no one text colour
    reads on all of them, while the better of black and white always reaches
    4.5:1. Alpha is ignored: the fill is judged by its RGB.
    """
    lum = _relative_luminance(fill)
    on_white = 1.05 / (lum + 0.05)
    on_black = (lum + 0.05) / 0.05
    return QColor(Qt.white) if on_white >= on_black else QColor(Qt.black)


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
