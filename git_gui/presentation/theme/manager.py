from __future__ import annotations
import logging
from typing import Optional
from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication
from .loader import load_builtin, load_theme, ThemeValidationError
from .qss_template import render
from .settings import load_settings, save_settings, custom_theme_path
from .tokens import Theme

_log = logging.getLogger(__name__)

_VALID_MODES = ("system", "light", "dark", "custom")


class ThemeManager(QObject):
    theme_changed = Signal(object)  # Theme

    def __init__(self, app: QApplication, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._app = app
        self._mode: str = load_settings().get("theme_mode", "system")
        if self._mode not in _VALID_MODES:
            self._mode = "system"
        self._current: Theme = self._resolve_theme()
        self._apply()

        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(self._on_system_scheme_changed)

    @property
    def current(self) -> Theme:
        return self._current

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        if mode not in _VALID_MODES:
            raise ValueError(f"Invalid theme mode: {mode}")
        if mode == self._mode:
            return
        self._mode = mode
        save_settings({"theme_mode": mode})
        self._refresh()

    def _refresh(self) -> None:
        new_theme = self._resolve_theme()
        if new_theme is self._current:
            return
        self._current = new_theme
        self._apply()
        self.theme_changed.emit(new_theme)

    def _apply(self) -> None:
        self._app.setStyleSheet(render(self._current))
        palette = _build_palette(self._current)
        self._app.setPalette(palette)
        # QApplication.setPalette only updates the *default* palette in
        # Qt 6 — already-shown widgets keep their inherited copy and
        # don't repaint. Walk every live widget and re-apply, then force
        # the viewport repaint for QAbstractScrollArea (tree/list/table
        # views, where update() on the view itself doesn't repaint
        # items).
        from PySide6.QtWidgets import QAbstractScrollArea
        style = self._app.style()
        for w in self._app.allWidgets():
            w.setPalette(palette)
            # Force re-evaluation of any inline stylesheet that uses
            # palette(role) references — Qt caches the resolved colors
            # and won't recompute on a palette change without a polish.
            if w.styleSheet():
                style.unpolish(w)
                style.polish(w)
            if isinstance(w, QAbstractScrollArea):
                w.viewport().update()
            w.update()

    def _resolve_theme(self) -> Theme:
        if self._mode == "light":
            return load_builtin("light")
        if self._mode == "dark":
            return load_builtin("dark")
        if self._mode == "custom":
            return self._load_custom_or_fallback()
        return self._system_theme()

    def _load_custom_or_fallback(self) -> Theme:
        from . import settings as _settings
        path = _settings.custom_theme_path()
        if not path.exists():
            _log.warning("Custom theme file not found at %s; falling back to dark", path)
            return load_builtin("dark")
        try:
            return load_theme(path)
        except (OSError, ThemeValidationError) as e:
            _log.warning("Could not load custom theme at %s: %s; falling back to dark", path, e)
            return load_builtin("dark")

    def _system_theme(self) -> Theme:
        hints = QGuiApplication.styleHints()
        scheme = getattr(hints, "colorScheme", lambda: Qt.ColorScheme.Light)()
        if scheme == Qt.ColorScheme.Dark:
            return load_builtin("dark")
        return load_builtin("light")

    def _on_system_scheme_changed(self, *_args) -> None:
        if self._mode == "system":
            self._refresh()


def _build_palette(theme: Theme) -> QPalette:
    """Map Theme colour tokens onto a QPalette so Qt's native widgets
    (main window background, list views, buttons, scrollbars, splitter,
    menu bar, line edits, etc.) follow the active theme without needing
    a global QSS rule that would break native scrollbar rendering."""
    c = theme.colors
    p = QPalette()

    bg          = QColor(c.background)
    on_bg       = QColor(c.on_background)
    surface     = QColor(c.surface)
    on_surface  = QColor(c.on_surface)
    surf_var    = QColor(c.surface_variant)
    on_surf_var = QColor(c.on_surface_variant)
    surf_cont   = QColor(c.surface_container)
    surf_high   = QColor(c.surface_container_high)
    primary     = QColor(c.primary)
    on_primary  = QColor(c.on_primary)
    error       = QColor(c.error)

    # Window / view backgrounds
    p.setColor(QPalette.Window,          bg)
    p.setColor(QPalette.WindowText,      on_bg)
    p.setColor(QPalette.Base,            surface)
    p.setColor(QPalette.AlternateBase,   surf_cont)
    p.setColor(QPalette.Text,            on_surface)
    p.setColor(QPalette.PlaceholderText, on_surf_var)

    # Buttons
    p.setColor(QPalette.Button,     surf_var)
    p.setColor(QPalette.ButtonText, on_surface)
    p.setColor(QPalette.BrightText, error)

    # Selection / highlight
    p.setColor(QPalette.Highlight,         primary)
    p.setColor(QPalette.HighlightedText,   on_primary)

    # Tooltips
    p.setColor(QPalette.ToolTipBase, surf_high)
    p.setColor(QPalette.ToolTipText, on_surface)

    # Links
    p.setColor(QPalette.Link,        primary)
    p.setColor(QPalette.LinkVisited, primary)

    # NOTE: Light / Midlight / Mid / Dark / Shadow are intentionally NOT
    # set. Qt expects Light > Window > Dark in luminance and uses these
    # to draw 3D bevels and menu-bar shading. Forcing them to arbitrary
    # theme tokens (which may invert the relationship in dark mode)
    # breaks native menu rendering on Windows. Letting Qt derive them
    # from Window/Button keeps the bevels consistent.

    # Disabled group — fade text/buttons toward on_surface_variant
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, on_surf_var)
    p.setColor(QPalette.Disabled, QPalette.Highlight, surf_var)
    p.setColor(QPalette.Disabled, QPalette.HighlightedText, on_surf_var)

    return p


_INSTANCE: Optional[ThemeManager] = None


def get_theme_manager() -> ThemeManager:
    if _INSTANCE is None:
        raise RuntimeError("ThemeManager not initialized; call set_theme_manager() first")
    return _INSTANCE


def set_theme_manager(mgr: ThemeManager) -> None:
    global _INSTANCE
    _INSTANCE = mgr
