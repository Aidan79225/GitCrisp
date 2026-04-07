from __future__ import annotations
import logging
from typing import Optional
from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QGuiApplication
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


_INSTANCE: Optional[ThemeManager] = None


def get_theme_manager() -> ThemeManager:
    if _INSTANCE is None:
        raise RuntimeError("ThemeManager not initialized; call set_theme_manager() first")
    return _INSTANCE


def set_theme_manager(mgr: ThemeManager) -> None:
    global _INSTANCE
    _INSTANCE = mgr
