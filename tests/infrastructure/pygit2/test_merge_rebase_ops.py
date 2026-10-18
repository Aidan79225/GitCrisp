"""MergeRebaseOps mixin — merge messages and rebase editor hooks."""

from __future__ import annotations

import subprocess
import sys
import tempfile

import pytest

from git_gui.infrastructure.pygit2 import Pygit2Repository


def _git(cwd, *args) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _commit_file(cwd, name: str, content: str, message: str) -> str:
    (cwd / name).write_text(content)
    _git(cwd, "add", name)
    _git(cwd, "commit", "-q", "-m", message)
    return _git(cwd, "rev-parse", "HEAD").strip()


def _subjects(cwd, rev: str = "HEAD") -> list[str]:
    return _git(cwd, "log", "--format=%s", rev).splitlines()


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "master")
    _git(path, "config", "user.email", "t@t")
    _git(path, "config", "user.name", "t")
    _commit_file(path, "a.txt", "base\n", "base")
    return path


@pytest.fixture
def frozen_app_executable(monkeypatch):
    """What sys.executable is in the PyInstaller release: the GitCrisp app
    itself, installed under a path with a space, and not a Python interpreter."""
    monkeypatch.setattr(sys, "executable", "C:/Program Files/GitCrisp/GitCrisp.exe")


# ── rebase editor hooks ──────────────────────────────────────────────────────


def test_interactive_rebase_applies_the_todo_without_a_python_interpreter(
    repo, frozen_app_executable
):
    base = _git(repo, "rev-parse", "HEAD").strip()
    keep = _commit_file(repo, "b.txt", "b\n", "keep me")
    drop = _commit_file(repo, "c.txt", "c\n", "drop me")

    Pygit2Repository(str(repo)).interactive_rebase(base, [("pick", keep), ("drop", drop)])

    assert _subjects(repo) == ["keep me", "base"]


def test_interactive_rebase_copes_with_a_quote_and_a_space_in_the_temp_dir(
    repo, tmp_path, monkeypatch
):
    awkward_temp = tmp_path / "O'Neil temp"
    awkward_temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(awkward_temp))
    base = _git(repo, "rev-parse", "HEAD").strip()
    keep = _commit_file(repo, "b.txt", "b\n", "keep me")
    drop = _commit_file(repo, "c.txt", "c\n", "drop me")

    Pygit2Repository(str(repo)).interactive_rebase(base, [("pick", keep), ("drop", drop)])

    assert _subjects(repo) == ["keep me", "base"]


def test_rebase_continue_commits_the_given_message_without_a_python_interpreter(
    repo, frozen_app_executable
):
    _git(repo, "checkout", "-q", "-b", "feature")
    _commit_file(repo, "a.txt", "feature\n", "feature change")
    _git(repo, "checkout", "-q", "master")
    _commit_file(repo, "a.txt", "master\n", "master change")
    _git(repo, "checkout", "-q", "feature")
    impl = Pygit2Repository(str(repo))
    with pytest.raises(RuntimeError):
        impl.rebase("master")
    (repo / "a.txt").write_text("resolved\n")
    _git(repo, "add", "a.txt")

    impl.rebase_continue("resolved it")

    assert _subjects(repo) == ["resolved it", "master change", "base"]
