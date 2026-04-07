import re

from git_gui.presentation.theme.loader import load_builtin
from git_gui.presentation.theme.qss_template import render

_PLACEHOLDER_RE = re.compile(r"%\([a-z_]+\)[sd]")


def test_render_light_has_no_placeholders():
    qss = render(load_builtin("light"))
    assert not _PLACEHOLDER_RE.search(qss)
    assert "QPushButton" in qss
    assert len(qss) > 200


def test_render_dark_has_no_placeholders():
    qss = render(load_builtin("dark"))
    assert not _PLACEHOLDER_RE.search(qss)
    assert "QPushButton" in qss
