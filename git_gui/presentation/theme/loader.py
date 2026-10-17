from __future__ import annotations

import json
import re
from dataclasses import fields
from importlib import resources
from pathlib import Path
from typing import Any

from .tokens import (
    Colors,
    Shape,
    Spacing,
    TextStyle,
    Theme,
    Typography,
)


class ThemeValidationError(ValueError):
    pass


_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")


def _check_hex(name: str, value: Any) -> None:
    if not isinstance(value, str) or not _HEX_RE.match(value):
        raise ThemeValidationError(f"{name}: invalid hex color {value!r}")


# JSON has a single number type, so a float field accepts a written 0.
_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "str": (str,),
    "int": (int,),
    "float": (int, float),
    "bool": (bool,),
}


def _check_type(path: str, value: Any, field_type: str) -> None:
    expected = _JSON_TYPES[field_type]
    # isinstance(True, int) holds, but a JSON true is never a size.
    is_stray_bool = isinstance(value, bool) and bool not in expected
    if is_stray_bool or not isinstance(value, expected):
        raise ThemeValidationError(f"{path}: expected {field_type}, got {value!r}")


def _check_keys(cls, data: Any, path: str) -> None:
    if not isinstance(data, dict):
        raise ThemeValidationError(f"{path}: must be an object")
    expected = {f.name for f in fields(cls)}
    given = set(data.keys())
    missing = expected - given
    extra = given - expected
    if missing:
        raise ThemeValidationError(f"{path}: missing key(s) {sorted(missing)}")
    if extra:
        raise ThemeValidationError(f"{path}: unknown key(s) {sorted(extra)}")


def _build_colors(data: dict) -> Colors:
    _check_keys(Colors, data, "colors")
    for k, v in data.items():
        if k == "graph_lane_colors":
            if not isinstance(v, list) or not v:
                raise ThemeValidationError("colors.graph_lane_colors: must be non-empty list")
            for i, c in enumerate(v):
                _check_hex(f"colors.graph_lane_colors[{i}]", c)
        else:
            _check_hex(f"colors.{k}", v)
    return Colors(**data)


def _build_typography(data: dict) -> Typography:
    _check_keys(Typography, data, "typography")
    return Typography(
        **{k: _build_simple(TextStyle, v, f"typography.{k}") for k, v in data.items()}
    )


def _build_simple(cls, data: Any, path: str):
    _check_keys(cls, data, path)
    for f in fields(cls):
        _check_type(f"{path}.{f.name}", data[f.name], f.type)
    return cls(**data)


_TOP_KEYS = {"name", "is_dark", "colors", "typography", "shape", "spacing"}


def _read_json(path: Path) -> Any:
    # utf-8-sig also reads the byte-order mark Windows editors prepend.
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except ValueError as e:  # JSONDecodeError and UnicodeDecodeError
        raise ThemeValidationError(f"root: not valid JSON ({e})") from e


def load_theme(path: Path) -> Theme:
    raw = _read_json(path)
    if not isinstance(raw, dict):
        raise ThemeValidationError("root: must be an object")
    given = set(raw.keys())
    missing = _TOP_KEYS - given
    extra = given - _TOP_KEYS
    if missing:
        raise ThemeValidationError(f"root: missing key(s) {sorted(missing)}")
    if extra:
        raise ThemeValidationError(f"root: unknown key(s) {sorted(extra)}")
    _check_type("name", raw["name"], "str")
    _check_type("is_dark", raw["is_dark"], "bool")
    return Theme(
        name=raw["name"],
        is_dark=bool(raw["is_dark"]),
        colors=_build_colors(raw["colors"]),
        typography=_build_typography(raw["typography"]),
        shape=_build_simple(Shape, raw["shape"], "shape"),
        spacing=_build_simple(Spacing, raw["spacing"], "spacing"),
    )


def load_builtin(name: str) -> Theme:
    if name not in ("light", "dark"):
        raise ValueError(f"Unknown builtin theme: {name}")
    with resources.as_file(
        resources.files("git_gui.presentation.theme.builtin") / f"{name}.json"
    ) as p:
        return load_theme(p)
