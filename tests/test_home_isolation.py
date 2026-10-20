"""The suite must never write to the developer's real ~/.gitcrisp.

Several tests build a MainWindow with ``JsonRepoStore()`` — no argument — which
defaults to ``~/.gitcrisp/repos.json``. An unloaded store is empty, and a repo
switch or a window teardown saves it, so without isolation running the tests
replaced the developer's open and recent repo lists with nothing. That data has
no backup: reconstructing it afterwards means matching sha256 prefixes of cache
filenames against directories on disk.
"""

from __future__ import annotations

import json
from pathlib import Path

from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.presentation.widgets.avatar_loader import AvatarLoader


def test_path_home_is_redirected(_isolated_gitcrisp_home):
    assert Path.home() == _isolated_gitcrisp_home


def test_default_repo_store_lands_in_the_fake_home(_isolated_gitcrisp_home):
    store = JsonRepoStore()

    assert _isolated_gitcrisp_home in store._path.parents


def test_saving_a_default_store_writes_only_under_the_fake_home(_isolated_gitcrisp_home):
    """The exact move that destroyed the real list: save an unloaded store."""
    store = JsonRepoStore()
    store.save()

    written = _isolated_gitcrisp_home / ".gitcrisp" / "repos.json"
    assert written.exists()
    assert json.loads(written.read_text(encoding="utf-8"))["open"] == []


def test_default_remote_tag_cache_lands_in_the_fake_home(_isolated_gitcrisp_home):
    cache = JsonRemoteTagCache()
    cache.save("C:/somewhere/repo", {"origin": ["v1.0.0"]})

    assert _isolated_gitcrisp_home in cache._dir.parents


def test_default_avatar_cache_lands_in_the_fake_home(_isolated_gitcrisp_home):
    loader = AvatarLoader()

    assert _isolated_gitcrisp_home in loader._cache_dir.parents


def test_theme_settings_land_in_the_fake_home(_isolated_gitcrisp_home):
    """Qt resolves AppDataLocation by itself, past every other redirect here."""
    from git_gui.presentation.theme.settings import custom_theme_path, settings_path

    assert _isolated_gitcrisp_home in settings_path().parents
    assert _isolated_gitcrisp_home in custom_theme_path().parents


def test_the_checkbox_tick_lands_in_the_fake_home(_isolated_gitcrisp_home):
    """Qt resolves CacheLocation by itself, and every ThemeManager writes the
    tinted tick there at startup, so each run left icons in the real cache."""
    import re

    from git_gui.presentation.theme.loader import load_builtin
    from git_gui.presentation.theme.qss_template import render

    qss = render(load_builtin("light"))
    match = re.search(r'QCheckBox::indicator:checked \{[^}]*image: url\("([^"]+)"\)', qss)

    assert match
    assert _isolated_gitcrisp_home in Path(match.group(1)).parents
