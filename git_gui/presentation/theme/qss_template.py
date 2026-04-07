from __future__ import annotations

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

/* Item view hover — Qt's default hover on Windows draws a hard white
   highlight when a global stylesheet is active. Use a subtle tint from
   surface_container_high so hover is visible in both light and dark. */
QAbstractItemView::item:hover {
    background: %(surface_container_high)s;
    color: %(on_surface)s;
}
QAbstractItemView::item:selected {
    background: %(primary)s;
    color: %(on_primary)s;
}

/* Radio / checkbox — keep transparent so Qt's native indicator (the
   dot / tick) handles hover. Only fix the text color. */
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
    border-color: %(primary)s;
}
QRadioButton::indicator:checked {
    border: 4px solid %(primary)s;
    background: %(surface)s;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border-radius: 3px;
    border: 2px solid %(outline)s;
    background: %(surface)s;
}
QCheckBox::indicator:hover {
    border-color: %(primary)s;
}
QCheckBox::indicator:checked {
    background: %(primary)s;
    border-color: %(primary)s;
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
        "surface": c.surface,
        "surface_variant": c.surface_variant,
        "surface_container_high": c.surface_container_high,
    }
