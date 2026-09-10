"""GitStack theming package — MD3-inspired tokens, loader, and manager."""

from .live import connect_widget
from .manager import ThemeManager, get_theme_manager, set_theme_manager
from .tokens import Colors, Shape, Spacing, TextStyle, Theme, Typography

__all__ = [
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
