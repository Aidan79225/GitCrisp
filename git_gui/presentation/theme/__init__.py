"""GitStack theming package — MD3-inspired tokens, loader, and manager."""
from .tokens import Theme, Colors, Typography, TextStyle, Shape, Spacing
from .manager import ThemeManager, get_theme_manager, set_theme_manager
from .live import connect_widget

__all__ = [
    "Theme", "Colors", "Typography", "TextStyle", "Shape", "Spacing",
    "ThemeManager", "get_theme_manager", "set_theme_manager",
    "connect_widget",
]
