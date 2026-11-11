from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

from PySide6.QtCore import QStandardPaths

_log = logging.getLogger(__name__)
DEFAULT_TYPOGRAPHY_SCALE = 1.0
# The Appearance slider's range; a scale read from settings.json is held to it too.
TYPOGRAPHY_SCALE_MIN = 0.5
TYPOGRAPHY_SCALE_MAX = 2.0
DEFAULTS = {
    "theme_mode": "system",
    "avatar_gravatar_enabled": True,
    "typography_scale": DEFAULT_TYPOGRAPHY_SCALE,
}


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


def load_typography_scale() -> float:
    """The saved text scale, always a finite number within the slider's range.

    settings.json is edited by hand as well as by the Appearance dialog, so
    the stored value can be any JSON. One that is not a finite number is
    replaced by the default, and a number outside the range is brought back
    into it.
    """
    raw = load_settings().get("typography_scale", DEFAULT_TYPOGRAPHY_SCALE)
    scale = _finite_float(raw)
    if scale is None:
        _log.warning(
            "Ignoring typography_scale %r in %s: not a finite number; using %s",
            raw,
            settings_path(),
            DEFAULT_TYPOGRAPHY_SCALE,
        )
        return DEFAULT_TYPOGRAPHY_SCALE
    return min(max(scale, TYPOGRAPHY_SCALE_MIN), TYPOGRAPHY_SCALE_MAX)


def _finite_float(value: Any) -> float | None:
    """*value* as a float, or None when it is not a finite number.

    A JSON boolean is not a number either: float(False) would be a scale of 0.
    """
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def save_settings(data: dict) -> None:
    p = settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
