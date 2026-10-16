"""GitStack theming package — MD3-inspired tokens, loader, and manager."""

from .live import connect_widget
from .manager import ThemeManager, get_theme_manager, set_theme_manager
from .qss_template import CHECKBOX_BORDER, CHECKBOX_INNER_SIZE, CHECKBOX_RADIUS
from .tokens import ColorRole, Colors, Shape, Spacing, TextStyle, Theme, Typography

__all__ = [
    "CHECKBOX_BORDER",
    "CHECKBOX_INNER_SIZE",
    "CHECKBOX_RADIUS",
    "ColorRole",
    "Colors",
    "Shape",
    "Spacing",
    "TextStyle",
    "Theme",
    "ThemeManager",
    "Typography",
    "connect_widget",
    "get_theme_manager",
    "set_theme_manager",
]
