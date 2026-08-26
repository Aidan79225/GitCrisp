"""Tests for path-filtered history — the CLI wrapper and its pygit2 adapter."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pygit2
import pytest

from git_gui.infrastructure.file_history_cli import FileHistoryCli, FileHistoryError
from git_gui.infrastructure.pygit2 import Pygit2Repository

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="file history shells out to the git CLI"
)


def _commit(repo: pygit2.Repository, path: Path, name: str, content: str, message: str) -> str:
    (path / name).write_text(content)
    repo.index.add(name)
    repo.index.write()
    sig = pygit2.Signature("Test User", "test@example.com")
    tree = repo.index.write_tree()
    return str(repo.create_commit("HEAD", sig, sig, message, tree, [repo.head.target]))


@pytest.fixture
def history_repo(repo_path) -> tuple[Pygit2Repository, Path, dict[str, str]]:
    """A repo where two files change independently, so filtering is observable."""
    raw = pygit2.Repository(str(repo_path))
    oids = {
        "a1": _commit(raw, repo_path, "a.txt", "a1\n", "add a"),
        "b1": _commit(raw, repo_path, "b.txt", "b1\n", "add b"),
        "a2": _commit(raw, repo_path, "a.txt", "a2\n", "change a"),
        "b2": _commit(raw, repo_path, "b.txt", "b2\n", "change b"),
    }
    return Pygit2Repository(str(repo_path)), repo_path, oids


# ── FileHistoryCli ───────────────────────────────────────────────────────────


def test_cli_returns_only_commits_touching_the_path(history_repo):
    _, path, oids = history_repo
    cli = FileHistoryCli(str(path))
    assert cli.commit_oids("a.txt", limit=50) == [oids["a2"], oids["a1"]]


def test_cli_respects_limit_and_skip(history_repo):
    _, path, oids = history_repo
    cli = FileHistoryCli(str(path))
    assert cli.commit_oids("a.txt", limit=1) == [oids["a2"]]
    assert cli.commit_oids("a.txt", limit=1, skip=1) == [oids["a1"]]


def test_cli_paginates_correctly_while_following(history_repo):
    """Paging must not repeat a commit when follow is on.

    git applies `--skip` before `--follow` re-derives the pathspec, so passing
    `--skip` straight through returned the newest commit again for page two.
    """
    _, path, oids = history_repo
    cli = FileHistoryCli(str(path))
    page1 = cli.commit_oids("a.txt", limit=1, skip=0, follow=True)
    page2 = cli.commit_oids("a.txt", limit=1, skip=1, follow=True)
    assert page1 == [oids["a2"]]
    assert page2 == [oids["a1"]]


def test_cli_unknown_path_returns_empty(history_repo):
    _, path, _ = history_repo
    assert FileHistoryCli(str(path)).commit_oids("never-existed.txt", limit=50) == []


def test_cli_follows_renames_when_asked(history_repo):
    """With follow, history continues past the rename into the old name's commits."""
    _, path, oids = history_repo
    subprocess.run(["git", "mv", "a.txt", "renamed.txt"], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=T", "-c", "user.email=t@e.com", "commit", "-m", "rename a"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    cli = FileHistoryCli(str(path))

    followed = cli.commit_oids("renamed.txt", limit=50, follow=True)
    assert oids["a1"] in followed, "follow should reach the file's pre-rename history"

    unfollowed = cli.commit_oids("renamed.txt", limit=50, follow=False)
    assert oids["a1"] not in unfollowed
    assert len(unfollowed) < len(followed)


def test_cli_missing_git_executable_raises(history_repo):
    _, path, _ = history_repo
    cli = FileHistoryCli(str(path), git_executable="definitely-not-a-real-git")
    with pytest.raises(FileHistoryError, match="not found on PATH"):
        cli.commit_oids("a.txt", limit=50)


# ── Pygit2Repository.get_file_history ────────────────────────────────────────


def test_get_file_history_hydrates_full_commit_entities(history_repo):
    impl, _, oids = history_repo
    commits = impl.get_file_history("a.txt", limit=50)

    assert [c.oid for c in commits] == [oids["a2"], oids["a1"]]
    # Entities must be indistinguishable from get_commits() output — the graph
    # model consumes them unchanged.
    assert commits[0].message == "change a"
    assert commits[0].author
    assert commits[0].parents == [oids["b1"]]


def test_get_file_history_paginates(history_repo):
    impl, _, oids = history_repo
    assert [c.oid for c in impl.get_file_history("a.txt", limit=1)] == [oids["a2"]]
    assert [c.oid for c in impl.get_file_history("a.txt", limit=1, skip=1)] == [oids["a1"]]


def test_get_file_history_unknown_path_is_empty(history_repo):
    impl, _, _ = history_repo
    assert impl.get_file_history("never-existed.txt", limit=50) == []
