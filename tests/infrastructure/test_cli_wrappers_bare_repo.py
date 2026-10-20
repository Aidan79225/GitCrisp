"""The git CLI wrappers work in a bare repository.

The app opens any folder `pygit2.discover_repository` accepts, a bare one
included. There pygit2 reports no working tree, and the wrappers must still
reach git rather than fail on the missing path.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from git_gui.infrastructure.pygit2 import Pygit2Repository

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs the git CLI")


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def bare_repo(tmp_path: Path) -> tuple[Path, str]:
    """A bare clone holding one commit that touches `f.txt`; returns (path, oid)."""
    source = tmp_path / "source"
    _git(tmp_path, "init", "-q", "-b", "master", str(source))
    (source / "f.txt").write_text("one", encoding="utf-8")
    _git(source, "add", "f.txt")
    _git(source, "commit", "-q", "-m", "one")
    bare = tmp_path / "bare.git"
    _git(tmp_path, "clone", "-q", "--bare", str(source), str(bare))
    return bare, _git(bare, "rev-parse", "HEAD")


def test_a_bare_repository_shows_a_file_s_history(bare_repo):
    bare, oid = bare_repo

    history = Pygit2Repository(str(bare)).get_file_history("f.txt", 10, 0)

    assert [commit.oid for commit in history] == [oid]


def test_cherry_pick_in_a_bare_repository_reports_git_s_own_reason(bare_repo):
    bare, oid = bare_repo

    with pytest.raises(RuntimeError, match="work tree"):
        Pygit2Repository(str(bare)).cherry_pick(oid)
