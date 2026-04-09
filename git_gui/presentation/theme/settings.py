from __future__ import annotations
import json
import logging
from pathlib import Path
from PySide6.QtCore import QStandardPaths

_log = logging.getLogger(__name__)
DEFAULTS = {"theme_mode": "system"}


def settings_path() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    return Path(base) / "GitStack" / "settings.json"


def custom_theme_path() -> Path:
    """Path to the user's saved custom theme JSON.

    Lives next to settings.json so the entire user theme state stays in
    one directory under <AppData>/GitStack/.
    """
    return settings_path().parent / "custom_theme.json"


def load_settings() -> dict:
    p = settings_path()
    if not p.exists():
        return dict(DEFAULTS)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("settings root must be an object")
        merged = dict(DEFAULTS)
        merged.update(data)
        return merged
    except (OSError, ValueError, json.JSONDecodeError) as e:
        _log.warning("Could not read settings at %s: %s; using defaults", p, e)
        return dict(DEFAULTS)


def save_settings(data: dict) -> None:
    p = settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
