"""The file paths Insight counts are the names users see, not git's quoted form."""

from __future__ import annotations

import shutil

import pygit2
import pytest

from git_gui.infrastructure.pygit2 import Pygit2Repository

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="stats shell out to git log")


def test_a_non_ascii_file_name_is_reported_as_written(repo_path):
    """With git's default core.quotepath, numstat prints `"\\346\\227\\245..."` instead."""
    raw = pygit2.Repository(str(repo_path))
    (repo_path / "日本語.txt").write_text("line\n", encoding="utf-8")
    raw.index.add("日本語.txt")
    raw.index.write()
    sig = pygit2.Signature("Test User", "test@example.com")
    raw.create_commit("HEAD", sig, sig, "add", raw.index.write_tree(), [raw.head.target])

    stats = Pygit2Repository(str(repo_path)).get_commit_stats()

    assert "日本語.txt" in [f.path for s in stats for f in s.files]
