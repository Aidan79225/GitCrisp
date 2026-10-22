"""Comparing paths as written, which the GUI thread can afford on any share."""

from __future__ import annotations

import os

from git_gui.presentation.paths import same_path_text


def test_spellings_of_one_path_are_the_same(tmp_path):
    repo = str(tmp_path / "repo")

    assert same_path_text(repo + os.sep, repo)
    assert same_path_text(str(tmp_path / "other" / ".." / "repo"), repo)


def test_different_paths_are_not(tmp_path):
    assert not same_path_text(str(tmp_path / "repo"), str(tmp_path / "repo-feature"))


def test_a_path_on_an_unreachable_share_is_compared_without_waiting():
    share = r"\\192.0.2.1\share\proj" if os.name == "nt" else "/mnt/192.0.2.1/proj"

    assert same_path_text(share, share + os.sep)
