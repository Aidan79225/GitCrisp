"""Regression test: links and checked indicators read on every surface.

Links, checked checkboxes and selected radios are drawn in
on_primary_container, with primary_container for the tick. primary is the
wrong token for them: the dark theme keeps it dark as a fill under
on_primary text, which left them at ~1.4:1 on the dark surface (#172).
"""

from __future__ import annotations

import pytest

from git_gui.presentation.theme.loader import load_builtin

from .test_light_contrast import _ratio

SURFACES = ["surface", "background", "surface_container", "surface_variant"]


@pytest.mark.parametrize("mode", ["dark", "light"])
@pytest.mark.parametrize("surface", SURFACES)
def test_accent_meets_text_contrast_on_surfaces(mode, surface):
    c = load_builtin(mode).colors
    ratio = _ratio(c.on_primary_container, getattr(c, surface))
    assert ratio >= 4.5, f"{mode}: on_primary_container on {surface} is {ratio:.2f}:1"


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_check_tick_stands_out_from_its_fill(mode):
    c = load_builtin(mode).colors
    ratio = _ratio(c.primary_container, c.on_primary_container)
    assert ratio >= 3.0, f"{mode}: tick on checked box is {ratio:.2f}:1"
