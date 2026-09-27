import re
from pathlib import Path

import pytest

from git_gui.presentation.theme.loader import load_builtin
from git_gui.presentation.theme.qss_template import render

_PLACEHOLDER_RE = re.compile(r"%\([a-z_]+\)[sd]")


def test_render_light_has_no_placeholders():
    qss = render(load_builtin("light"))
    assert not _PLACEHOLDER_RE.search(qss)


def test_render_dark_has_no_placeholders():
    qss = render(load_builtin("dark"))
    assert not _PLACEHOLDER_RE.search(qss)


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_check_icon_is_an_absolute_path_in_the_theme_color(mode, tmp_path, monkeypatch):
    """A relative url() resolves against the working directory, so an
    installed build (never run from the project root) drew no tick."""
    monkeypatch.chdir(tmp_path)
    theme = load_builtin(mode)
    match = re.search(r"QCheckBox::indicator:checked \{[^}]*image: url\(([^)]+)\)", render(theme))
    assert match
    icon = Path(match.group(1))
    assert icon.is_absolute()
    assert theme.colors.primary_container in icon.read_text(encoding="utf-8")
