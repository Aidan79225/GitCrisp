from __future__ import annotations

from .tokens import Theme

# QSS template — colors only. No padding/margin/min-size rules so widget
# layout matches the original (pre-theme) behavior.
QSS_TEMPLATE = """
QWidget {
    background-color: %(surface)s;
    color: %(on_surface)s;
    font-size: %(body_size)dpx;
}

QMainWindow, QDialog {
    background-color: %(background)s;
    color: %(on_background)s;
}

QPushButton {
    background-color: %(primary_container)s;
    color: %(on_primary_container)s;
    border: 1px solid %(outline_variant)s;
    border-radius: %(corner_sm)dpx;
}
QPushButton:hover  { background-color: %(primary)s; color: %(on_primary)s; }
QPushButton:pressed{ background-color: %(primary)s; color: %(on_primary)s; }
QPushButton:disabled { color: %(outline)s; border-color: %(outline_variant)s; }

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox {
    background-color: %(surface_container)s;
    color: %(on_surface)s;
    border: 1px solid %(outline_variant)s;
    border-radius: %(corner_xs)dpx;
    selection-background-color: %(primary)s;
    selection-color: %(on_primary)s;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {
    border: 1px solid %(primary)s;
}

QTabWidget::pane {
    border: 1px solid %(outline_variant)s;
    background-color: %(surface)s;
}
QTabBar::tab {
    background: %(surface_container)s;
    color: %(on_surface_variant)s;
}
QTabBar::tab:selected {
    background: %(surface_container_high)s;
    color: %(on_surface)s;
}

QMenu {
    background-color: %(surface_container_high)s;
    color: %(on_surface)s;
    border: 1px solid %(outline_variant)s;
}
QMenu::item:selected { background-color: %(primary_container)s; color: %(on_primary_container)s; }

QMenuBar {
    background-color: %(surface)s;
    color: %(on_surface)s;
}
QMenuBar::item:selected { background-color: %(primary_container)s; color: %(on_primary_container)s; }

QScrollBar:vertical, QScrollBar:horizontal {
    background: %(surface)s;
    border: none;
}
QScrollBar::handle {
    background: %(outline_variant)s;
    border-radius: 4px;
}
QScrollBar::handle:hover { background: %(outline)s; }
QScrollBar::add-line, QScrollBar::sub-line { background: none; border: none; }

QToolTip {
    background-color: %(surface_container_high)s;
    color: %(on_surface)s;
    border: 1px solid %(outline_variant)s;
}

QHeaderView::section {
    background-color: %(surface_container)s;
    color: %(on_surface_variant)s;
    border: none;
    border-right: 1px solid %(outline_variant)s;
}

QListView, QTreeView, QTableView {
    background-color: %(surface)s;
    alternate-background-color: %(surface_container)s;
    color: %(on_surface)s;
    selection-background-color: %(primary_container)s;
    selection-color: %(on_primary_container)s;
    border: 1px solid %(outline_variant)s;
}

QSplitter::handle { background-color: %(outline_variant)s; }

QStatusBar {
    background-color: %(surface_container)s;
    color: %(on_surface_variant)s;
}

QGroupBox {
    border: 1px solid %(outline_variant)s;
    border-radius: %(corner_xs)dpx;
}
QGroupBox::title { color: %(on_surface_variant)s; }

QCheckBox, QRadioButton { color: %(on_surface)s; }
"""


def render(theme: Theme) -> str:
    c = theme.colors
    sh = theme.shape
    body = theme.typography.body_medium
    mapping = {
        "background": c.background,
        "on_background": c.on_background,
        "surface": c.surface,
        "on_surface": c.on_surface,
        "surface_variant": c.surface_variant,
        "on_surface_variant": c.on_surface_variant,
        "surface_container": c.surface_container,
        "surface_container_high": c.surface_container_high,
        "primary": c.primary,
        "on_primary": c.on_primary,
        "primary_container": c.primary_container,
        "on_primary_container": c.on_primary_container,
        "outline": c.outline,
        "outline_variant": c.outline_variant,
        "corner_xs": sh.corner_xs,
        "corner_sm": sh.corner_sm,
        "corner_md": sh.corner_md,
        "body_size": body.size,
    }
    return QSS_TEMPLATE % mapping
