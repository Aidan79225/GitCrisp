from __future__ import annotations

import logging
import sys
from enum import StrEnum

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QWidget

from .loader import ThemeValidationError, load_builtin, load_theme
from .qss_template import render
from .settings import load_settings, save_settings
from .tokens import Theme

_log = logging.getLogger(__name__)


class ThemeMode(StrEnum):
    """Which theme the app shows; the values are what settings.json stores.

    Listed in the order the Appearance dialog offers them.
    """

    SYSTEM = "system"
    DARK = "dark"
    LIGHT = "light"
    CUSTOM = "custom"


# Theme sizes are calibrated for the Windows body text size.
_WINDOWS_BODY_PT = 9


class ThemeManager(QObject):
    theme_changed = Signal(object)  # Theme

    def __init__(self, app: QApplication, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._app = app
        saved = load_settings().get("theme_mode")
        self._mode = ThemeMode(saved) if saved in ThemeMode else ThemeMode.SYSTEM
        self._current: Theme = self._resolve_theme()
        self._apply()

        # QStyleHints.colorScheme/colorSchemeChanged have existed since Qt 6.5
        # and the project pins PySide6 >= 6.11, so these are read directly. A
        # hasattr guard here would turn a rename into "system theme following
        # quietly stopped working" rather than a crash that says what broke.
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_system_scheme_changed)

    @property
    def current(self) -> Theme:
        return self._current

    @property
    def mode(self) -> ThemeMode:
        return self._mode

    def set_mode(self, mode: ThemeMode, force: bool = False) -> None:
        mode = ThemeMode(mode)
        if mode is self._mode and not force:
            return
        self._save_and_adopt(mode, {})

    def set_appearance(self, mode: ThemeMode, typography_scale: float) -> None:
        """Adopt a mode and text scale together: both are saved, or neither."""
        self._save_and_adopt(ThemeMode(mode), {"typography_scale": typography_scale})

    def _save_and_adopt(self, mode: ThemeMode, other_settings: dict) -> None:
        # Saved before it is adopted, so a write that raises leaves the old
        # mode in force, which is also the one still on screen.
        data = load_settings()
        data.update(other_settings, theme_mode=mode)
        save_settings(data)
        self._mode = mode
        self._refresh()

    def _refresh(self) -> None:
        self._current = self._resolve_theme()
        self._apply()
        self.theme_changed.emit(self._current)

    def _apply(self) -> None:
        self._app.setStyleSheet(render(self._current))
        palette = _build_palette(self._current)
        self._app.setPalette(palette)
        font = self._theme_font()
        self._app.setFont(font)
        self._restyle_live_widgets(palette, font)

    def _theme_font(self) -> QFont:
        """The app font in the theme's body style, at the saved text scale."""
        body = self._current.typography.body_medium
        font = QFont(self._app.font())
        if body.family:
            font.setFamily(body.family)
        if body.size > 0:
            scale = float(load_settings().get("typography_scale", 1.0))
            font.setPointSize(_scaled_point_size(body.size, scale))
        if body.weight:
            font.setWeight(QFont.Weight(body.weight))
        return font

    def _restyle_live_widgets(self, palette: QPalette, font: QFont) -> None:
        # QApplication.setPalette only updates the *default* palette in
        # Qt 6 — already-shown widgets keep their inherited copy and
        # don't repaint. Walk every live widget and re-apply, then force
        # the viewport repaint for QAbstractScrollArea (tree/list/table
        # views, where update() on the view itself doesn't repaint
        # items).
        style = self._app.style()
        for w in self._app.allWidgets():
            w.setPalette(palette)
            w.setFont(_font_for(w, font))
            # Force re-evaluation of any inline stylesheet that uses
            # palette(role) references — Qt caches the resolved colors
            # and won't recompute on a palette change without a polish.
            if w.styleSheet():
                style.unpolish(w)
                style.polish(w)
            if isinstance(w, QAbstractScrollArea):
                w.viewport().update()
            w.update()

    def theme_for_mode(self, mode: ThemeMode) -> Theme:
        """Resolve a mode to a Theme without changing the active mode."""
        mode = ThemeMode(mode)
        if mode is ThemeMode.LIGHT:
            return load_builtin("light")
        if mode is ThemeMode.DARK:
            return load_builtin("dark")
        if mode is ThemeMode.CUSTOM:
            return self._load_custom_or_fallback()
        return self._system_theme()

    def _resolve_theme(self) -> Theme:
        return self.theme_for_mode(self._mode)

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
        scheme = QGuiApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return load_builtin("dark")
        return load_builtin("light")

    def _on_system_scheme_changed(self, *_args) -> None:
        if self._mode is ThemeMode.SYSTEM:
            self._refresh()


def _scaled_point_size(theme_size: int, scale: float) -> int:
    size = max(1, round(theme_size * scale))
    if sys.platform != "darwin":
        return size
    # macOS body text is about 13 pt against Windows' 9, so the theme's
    # sizes grow by the native size to keep the same proportion.
    native_pt = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).pointSize()
    if native_pt <= 0:
        return size
    return round(size * native_pt / _WINDOWS_BODY_PT)


def _font_for(widget: QWidget, theme_font: QFont) -> QFont:
    """The theme font beneath whatever the widget set for itself.

    A widget keeps the attributes it chose (Courier New in the commit
    message, a bold header) and takes the rest from the theme. One that
    chose nothing gets an empty font, which makes it inherit the
    application font again: under an application style sheet Qt does not
    pass that down to child widgets on its own.
    """
    if widget.testAttribute(Qt.WA_SetFont):
        return widget.font().resolve(theme_font)
    return QFont()


def _build_palette(theme: Theme) -> QPalette:
    """Map Theme colour tokens onto a QPalette so Qt's native widgets
    (main window background, list views, buttons, scrollbars, splitter,
    menu bar, line edits, etc.) follow the active theme without needing
    a global QSS rule that would break native scrollbar rendering."""
    c = theme.colors
    p = QPalette()

    bg = QColor(c.background)
    on_bg = QColor(c.on_background)
    surface = QColor(c.surface)
    on_surface = QColor(c.on_surface)
    surf_var = QColor(c.surface_variant)
    on_surf_var = QColor(c.on_surface_variant)
    surf_cont = QColor(c.surface_container)
    surf_high = QColor(c.surface_container_high)
    primary = QColor(c.primary)
    on_primary = QColor(c.on_primary)
    error = QColor(c.error)

    # Window / view backgrounds
    p.setColor(QPalette.Window, bg)
    p.setColor(QPalette.WindowText, on_bg)
    p.setColor(QPalette.Base, surface)
    p.setColor(QPalette.AlternateBase, surf_cont)
    p.setColor(QPalette.Text, on_surface)
    p.setColor(QPalette.PlaceholderText, on_surf_var)

    # Buttons
    p.setColor(QPalette.Button, surf_var)
    p.setColor(QPalette.ButtonText, on_surface)
    p.setColor(QPalette.BrightText, error)

    # Selection / highlight
    p.setColor(QPalette.Highlight, primary)
    p.setColor(QPalette.HighlightedText, on_primary)

    # Tooltips
    p.setColor(QPalette.ToolTipBase, surf_high)
    p.setColor(QPalette.ToolTipText, on_surface)

    # Links. Not primary: that is a fill under on_primary text, and the dark
    # theme's primary is too dark to read as text on its surfaces.
    link = QColor(c.on_primary_container)
    p.setColor(QPalette.Link, link)
    p.setColor(QPalette.LinkVisited, link)

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


_INSTANCE: ThemeManager | None = None


def get_theme_manager() -> ThemeManager:
    if _INSTANCE is None:
        raise RuntimeError("ThemeManager not initialized; call set_theme_manager() first")
    return _INSTANCE


def set_theme_manager(mgr: ThemeManager) -> None:
    global _INSTANCE
    _INSTANCE = mgr
