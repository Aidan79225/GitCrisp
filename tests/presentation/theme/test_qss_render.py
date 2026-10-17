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


def _check_icon_in(qss: str) -> Path:
    match = re.search(r"QCheckBox::indicator:checked \{[^}]*image: url\(([^)]+)\)", qss)
    assert match
    return Path(match.group(1))


def test_check_icon_is_written_to_this_users_own_cache():
    """On Linux the temp directory is the shared /tmp: a directory another
    user created there made the write fail at launch, and a symlink they
    planted in it redirected the write into this user's files."""
    from PySide6.QtCore import QStandardPaths

    cache = Path(QStandardPaths.writableLocation(QStandardPaths.CacheLocation))
    assert _check_icon_in(render(load_builtin("light"))).is_relative_to(cache)


def test_a_check_icon_that_cannot_be_written_still_leaves_a_tick(tmp_path, monkeypatch):
    """render() runs inside ThemeManager.__init__, so an OSError here used
    to stop the app before any window opened."""
    from git_gui.presentation.theme import qss_template

    not_a_directory = tmp_path / "file"
    not_a_directory.write_text("", encoding="utf-8")
    monkeypatch.setattr(qss_template, "_icon_dir", lambda: not_a_directory / "icons")

    assert _check_icon_in(render(load_builtin("light"))).exists()
