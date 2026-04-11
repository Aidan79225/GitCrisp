"""Tests for repo_list helpers."""
from __future__ import annotations
from pathlib import Path

from git_gui.presentation.widgets.repo_list import _display_path


def test_display_path_under_home(monkeypatch, tmp_path):
    fake_home = tmp_path / "user"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    result = _display_path(str(fake_home / "projects" / "GitStack"))

    assert result == "~/projects/GitStack"


def test_display_path_outside_home(monkeypatch, tmp_path):
    fake_home = tmp_path / "user"
    fake_home.mkdir()
    outside = tmp_path / "elsewhere" / "Repo"
    outside.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    result = _display_path(str(outside))

    # Outside-of-home path should come back unchanged (with forward slashes)
    assert "\\" not in result
    assert result.endswith("elsewhere/Repo")
    assert "~" not in result


def test_display_path_home_itself(monkeypatch, tmp_path):
    fake_home = tmp_path / "user"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    result = _display_path(str(fake_home))

    assert result == "~"


def test_display_path_uses_forward_slashes(monkeypatch, tmp_path):
    fake_home = tmp_path / "user"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    result = _display_path(str(fake_home / "a" / "b" / "c"))

    assert "\\" not in result
    assert result == "~/a/b/c"
