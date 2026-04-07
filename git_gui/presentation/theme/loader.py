from __future__ import annotations
import json
import re
from dataclasses import fields
from importlib import resources
from pathlib import Path
from typing import Any
from .tokens import (
    Theme, Colors, Typography, TextStyle, Shape, Spacing,
)


class ThemeValidationError(ValueError):
    pass


_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")


def _check_hex(name: str, value: Any) -> None:
    if not isinstance(value, str) or not _HEX_RE.match(value):
        raise ThemeValidationError(f"{name}: invalid hex color {value!r}")


def _check_keys(cls, data: dict, path: str) -> None:
    expected = {f.name for f in fields(cls)}
    given = set(data.keys())
    missing = expected - given
    extra = given - expected
    if missing:
        raise ThemeValidationError(f"{path}: missing key(s) {sorted(missing)}")
    if extra:
        raise ThemeValidationError(f"{path}: unknown key(s) {sorted(extra)}")


def _build_text_style(data: dict, path: str) -> TextStyle:
    _check_keys(TextStyle, data, path)
    return TextStyle(**data)


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
    return Typography(**{
        k: _build_text_style(v, f"typography.{k}") for k, v in data.items()
    })


def _build_simple(cls, data: dict, path: str):
    _check_keys(cls, data, path)
    return cls(**data)


_TOP_KEYS = {"name", "is_dark", "colors", "typography", "shape", "spacing"}


def load_theme(path: Path) -> Theme:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ThemeValidationError("root: must be an object")
    given = set(raw.keys())
    missing = _TOP_KEYS - given
    extra = given - _TOP_KEYS
    if missing:
        raise ThemeValidationError(f"root: missing key(s) {sorted(missing)}")
    if extra:
        raise ThemeValidationError(f"root: unknown key(s) {sorted(extra)}")
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
