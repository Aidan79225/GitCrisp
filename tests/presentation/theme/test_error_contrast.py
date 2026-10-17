"""Regression test: text drawn on the error colour reads in every theme.

The commit view's merge and rebase banner draws its label and buttons in
on_error over error. White on the dark theme's error was 3.35:1, short of
AA for body text. The fix darkened on_error rather than error, because error
is also drawn as text on the dark surfaces and has no contrast to give up.
"""

from __future__ import annotations

import pytest

from git_gui.presentation.theme.loader import load_builtin

from .test_light_contrast import _ratio


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_on_error_text_meets_aa_on_error(mode):
    c = load_builtin(mode).colors
    ratio = _ratio(c.on_error, c.error)
    assert ratio >= 4.5, f"{mode}: on_error {c.on_error} on error {c.error} is {ratio:.2f}:1"


@pytest.mark.parametrize("mode", ["dark", "light"])
@pytest.mark.parametrize("surface", ["surface", "background"])
def test_error_text_meets_aa_on_surfaces(mode, surface):
    c = load_builtin(mode).colors
    ratio = _ratio(c.error, getattr(c, surface))
    assert ratio >= 4.5, f"{mode}: error {c.error} on {surface} is {ratio:.2f}:1"
