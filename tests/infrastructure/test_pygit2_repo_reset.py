from __future__ import annotations
import subprocess
from pathlib import Path
import pytest
import pygit2

from git_gui.domain.entities import ResetMode
from git_gui.infrastructure.pygit2_repo import Pygit2Repository


@pytest.fixture
def three_commit_repo(tmp_path: Path) -> tuple[Pygit2Repository, str, str, str]:
    """master with 3 commits. Returns (impl, first_sha, second_sha, third_sha)."""
    def _run(*args):
        subprocess.run(["git", *args], cwd=str(tmp_path), check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    _run("init", "-q", "-b", "master")
    _run("config", "user.email", "t@t")
    _run("config", "user.name", "t")

    def _commit(name: str, content: str, msg: str) -> str:
        (tmp_path / name).write_text(content)
        _run("add", name)
        _run("commit", "-m", msg)
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(tmp_path),
            capture_output=True, text=True, check=True,
        )
        return r.stdout.strip()

    first = _commit("a.txt", "a\n", "first")
    second = _commit("b.txt", "b\n", "second")
    third = _commit("c.txt", "c\n", "third")
    return Pygit2Repository(str(tmp_path)), first, second, third


def _head_sha(repo_path: Path) -> str:
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo_path),
        capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


def test_reset_soft_moves_head_only(three_commit_repo, tmp_path):
    impl, first, _second, _third = three_commit_repo
    impl.reset_to(first, ResetMode.SOFT)
    # HEAD is now first; index still has b.txt and c.txt staged.
    assert _head_sha(tmp_path) == first
    # Working tree untouched.
    assert (tmp_path / "b.txt").exists()
    assert (tmp_path / "c.txt").exists()
    # Both files are staged (index entries for them).
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=str(tmp_path),
        capture_output=True, text=True, check=True,
    ).stdout
    assert "A  b.txt" in status
    assert "A  c.txt" in status


def test_reset_mixed_keeps_working_tree_resets_index(three_commit_repo, tmp_path):
    impl, first, _second, _third = three_commit_repo
    impl.reset_to(first, ResetMode.MIXED)
    assert _head_sha(tmp_path) == first
    assert (tmp_path / "b.txt").exists()
    assert (tmp_path / "c.txt").exists()
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=str(tmp_path),
        capture_output=True, text=True, check=True,
    ).stdout
    # Now b.txt / c.txt are untracked (??), not staged.
    assert "?? b.txt" in status
    assert "?? c.txt" in status


def test_reset_hard_discards_everything(three_commit_repo, tmp_path):
    impl, first, _second, _third = three_commit_repo
    impl.reset_to(first, ResetMode.HARD)
    assert _head_sha(tmp_path) == first
    assert not (tmp_path / "b.txt").exists()
    assert not (tmp_path / "c.txt").exists()


def test_reset_to_head_is_noop(three_commit_repo, tmp_path):
    impl, _first, _second, third = three_commit_repo
    impl.reset_to(third, ResetMode.HARD)
    assert _head_sha(tmp_path) == third
    assert (tmp_path / "a.txt").exists()
    assert (tmp_path / "b.txt").exists()
    assert (tmp_path / "c.txt").exists()
