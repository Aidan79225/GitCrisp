"""Remote operations on refs whose names are not ASCII.

git prints ref names as UTF-8 whatever the OS locale. On Windows the locale
code page (cp1252, cp950, ...) cannot decode every UTF-8 byte; "Ł" is one such
character for both, so these tests fail there if the output is decoded with it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from git_gui.infrastructure.pygit2 import Pygit2Repository

BRANCH = "Łódź"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def published(repo_path: Path, tmp_path: Path) -> Path:
    """repo_path with BRANCH pushed to a bare `origin` and checked out."""
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", str(remote))
    _git(repo_path, "remote", "add", "origin", str(remote))
    _git(repo_path, "checkout", "-q", "-b", BRANCH)
    _git(repo_path, "push", "-q", "origin", BRANCH)
    return repo_path


def test_deleting_a_non_ascii_remote_branch_reports_success(published):
    results = Pygit2Repository(str(published)).delete_remote_branches("origin", [BRANCH])
    assert [(r.branch, r.ok) for r in results] == [(f"origin/{BRANCH}", True)]


def test_a_rejected_push_of_a_non_ascii_branch_carries_gits_reason(published):
    _git(published, "commit", "-q", "--amend", "--allow-empty", "-m", "rewritten")
    with pytest.raises(RuntimeError, match="non-fast-forward"):
        Pygit2Repository(str(published)).push("origin", BRANCH)
