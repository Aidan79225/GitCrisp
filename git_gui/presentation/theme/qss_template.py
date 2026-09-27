from __future__ import annotations

import tempfile
from pathlib import Path

from git_gui.resources import get_resource_path

from .tokens import Theme

# Targeted global QSS rules for chrome elements that Qt's native styles
# don't fully reach via QPalette alone (notably QMenuBar / QMenu on
# Windows, which on some platforms ignore WindowText for item text).
#
# Selectors are intentionally narrow — never use bare `QWidget` or
# anything that cascades to QScrollBar, or you'll trip Qt out of native
# scrollbar rendering. See git history of qss_template.py for the
# scrollbar incident.

QSS_TEMPLATE = """
QMenuBar {
    background-color: %(background)s;
    color: %(on_background)s;
    border-bottom: 1px solid %(outline_variant)s;
}
QMenuBar::item {
    background: transparent;
    color: %(on_background)s;
}
QMenuBar::item:selected {
    background: %(primary)s;
    color: %(on_primary)s;
}
QMenuBar::item:disabled {
    color: %(on_surface_variant)s;
}

QMenu {
    background-color: %(surface_container)s;
    color: %(on_surface)s;
    border: 1px solid %(outline_variant)s;
}
QMenu::item {
    background: transparent;
    color: %(on_surface)s;
}
QMenu::item:selected {
    background: %(primary)s;
    color: %(on_primary)s;
}
QMenu::item:disabled {
    color: %(on_surface_variant)s;
}
QMenu::separator {
    height: 1px;
    background: %(outline_variant)s;
}

/* QDialogButtonBox / generic dialog buttons — once a global stylesheet
   exists, Qt's native button rendering on Windows can drop palette
   colors and end up drawing white-on-white. Force readable colors. */
QDialog QPushButton {
    background-color: %(surface_variant)s;
    color: %(on_surface)s;
    border: 1px solid %(outline)s;
    border-radius: 4px;
    padding: 4px 12px;
    min-width: 72px;
}
QDialog QPushButton:hover {
    background-color: %(surface_container_high)s;
}
QDialog QPushButton:pressed {
    background-color: %(primary)s;
    color: %(on_primary)s;
}
QDialog QPushButton:disabled {
    color: %(on_surface_variant)s;
}

/* Item view selection only — per-item hover is left to widget-level
   delegates so views that paint full-row hover don't get a second
   highlight on top. */
QAbstractItemView::item:selected {
    background: %(primary)s;
    color: %(on_primary)s;
}
QAbstractItemView {
    outline: 0;
}
QAbstractItemView::item {
    border: none;
}
QAbstractItemView::item:hover {
    background: transparent;
}
QTreeView::branch:hover {
    background: transparent;
}

/* Radio / checkbox — keep transparent so Qt's native indicator (the
   dot / tick) handles hover. Only fix the text color.

   The checked state is drawn in on_primary_container, not primary: primary
   is the fill for selected rows under on_primary text, so the dark theme
   keeps it dark, and a dark indicator on a dark surface all but vanishes.
   on_primary_container is the accent that reads on the surface in both
   themes, and primary_container is its matching glyph color. */
QRadioButton, QCheckBox {
    background: transparent;
    color: %(on_surface)s;
}
QRadioButton::indicator {
    width: 14px;
    height: 14px;
    border-radius: 8px;
    border: 2px solid %(outline)s;
    background: %(surface)s;
}
QRadioButton::indicator:hover {
    border-color: %(on_primary_container)s;
}
QRadioButton::indicator:checked {
    border: 2px solid %(on_primary_container)s;
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5,
        fx:0.5, fy:0.5,
        stop:0 %(on_primary_container)s, stop:0.55 %(on_primary_container)s,
        stop:0.6 %(surface)s, stop:1 %(surface)s);
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border-radius: 3px;
    border: 2px solid %(outline)s;
    background: %(surface)s;
}
QCheckBox::indicator:hover {
    border-color: %(on_primary_container)s;
}
QCheckBox::indicator:checked {
    background: %(on_primary_container)s;
    border-color: %(on_primary_container)s;
    image: url(%(check_icon)s);
}

/* Scrollbar — once any QApplication stylesheet exists, Qt routes
   scrollbars through stylesheet rendering and we lose the native
   hover-to-expand effect. Re-create it via the :hover pseudo-state:
   the outer track stays a fixed 12px (so layout never shifts) and the
   handle's margin shrinks on hover, visually thickening it. */
QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 0px;
    border: none;
}
QScrollBar:horizontal {
    background: transparent;
    height: 12px;
    margin: 0px;
    border: none;
}
QScrollBar::handle:vertical {
    background: %(outline)s;
    min-height: 24px;
    border-radius: 3px;
    margin: 4px 4px 4px 4px;
}
QScrollBar::handle:horizontal {
    background: %(outline)s;
    min-width: 24px;
    border-radius: 3px;
    margin: 4px 4px 4px 4px;
}
QScrollBar:vertical:hover {
    background: %(surface_container)s;
}
QScrollBar:horizontal:hover {
    background: %(surface_container)s;
}
QScrollBar::handle:vertical:hover {
    background: %(on_surface_variant)s;
    margin: 2px 2px 2px 2px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal:hover {
    background: %(on_surface_variant)s;
    margin: 2px 2px 2px 2px;
    border-radius: 4px;
}
QScrollBar::add-line, QScrollBar::sub-line {
    background: none;
    border: none;
    width: 0px;
    height: 0px;
}
QScrollBar::add-page, QScrollBar::sub-page {
    background: none;
}
"""


def _check_icon(color: str) -> str:
    """Path to the checkbox tick drawn in ``color``, for a QSS ``url()``.

    A QSS image cannot be recolored, so the tick is written out once per
    color. The path is absolute: a relative ``url()`` resolves against the
    working directory, which is only the project root when run from a
    checkout, so an installed build showed no tick at all.
    """
    template = get_resource_path("arts/ic_check.svg").read_text(encoding="utf-8")
    svg = template.replace("#fff", color)
    icon = Path(tempfile.gettempdir()) / "gitcrisp" / f"ic_check_{color.lstrip('#')}.svg"
    if not icon.exists() or icon.read_text(encoding="utf-8") != svg:
        icon.parent.mkdir(parents=True, exist_ok=True)
        icon.write_text(svg, encoding="utf-8")
    return icon.as_posix()


def render(theme: Theme) -> str:
    c = theme.colors
    return QSS_TEMPLATE % {
        "background": c.background,
        "on_background": c.on_background,
        "surface_container": c.surface_container,
        "on_surface": c.on_surface,
        "on_surface_variant": c.on_surface_variant,
        "outline": c.outline,
        "outline_variant": c.outline_variant,
        "primary": c.primary,
        "on_primary": c.on_primary,
        "on_primary_container": c.on_primary_container,
        "check_icon": _check_icon(c.primary_container),
        "surface": c.surface,
        "surface_variant": c.surface_variant,
        "surface_container_high": c.surface_container_high,
    }
