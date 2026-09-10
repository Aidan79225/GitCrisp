"""Regression test: Light theme meets WCAG AA contrast.

Locks in the contrast budget documented in
docs/superpowers/specs/2026-05-05-light-theme-softer-design.md so future
edits to surface or text tokens can't silently regress readability. The
worst-case pair (muted text on the deepest tinted surface) is the
binding constraint at ~5:1 — well above the 4.5:1 AA threshold but
close enough that careless tweaks could break it.
"""

from __future__ import annotations

import pytest

from git_gui.presentation.theme.loader import load_builtin


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _ratio(fg: str, bg: str) -> float:
    a, b = _luminance(fg), _luminance(bg)
    if a < b:
        a, b = b, a
    return (a + 0.05) / (b + 0.05)


@pytest.fixture(scope="module")
def light_colors():
    return load_builtin("light").colors


@pytest.mark.parametrize(
    "fg_attr, bg_attr, label",
    [
        ("on_surface", "surface", "body text on surface"),
        ("on_surface", "surface_container_high", "body text on container_high"),
        ("on_surface_variant", "surface_variant", "muted text on surface_variant"),
        ("on_surface_variant", "surface_container_high", "muted text on container_high"),
        ("on_primary", "primary", "primary button label"),
    ],
)
def test_light_theme_passes_wcag_aa(light_colors, fg_attr, bg_attr, label):
    fg = getattr(light_colors, fg_attr)
    bg = getattr(light_colors, bg_attr)
    ratio = _ratio(fg, bg)
    assert ratio >= 4.5, f"{label}: {fg_attr} {fg} on {bg_attr} {bg} = {ratio:.2f}:1 (need ≥ 4.5)"
