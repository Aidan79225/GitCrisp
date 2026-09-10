"""Tests for per-line blame."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pygit2
import pytest

from git_gui.infrastructure.pygit2 import Pygit2Repository


def _commit(
    repo: pygit2.Repository,
    path: Path,
    name: str,
    content: str,
    message: str,
    *,
    author: pygit2.Signature | None = None,
) -> str:
    (path / name).write_text(content)
    repo.index.add(name)
    repo.index.write()
    sig = pygit2.Signature("Test User", "test@example.com")
    tree = repo.index.write_tree()
    return str(repo.create_commit("HEAD", author or sig, sig, message, tree, [repo.head.target]))


@pytest.fixture
def blame_repo(repo_path) -> tuple[Pygit2Repository, Path, dict[str, str]]:
    """A file whose three lines were each last touched by a different commit."""
    raw = pygit2.Repository(str(repo_path))
    oids = {
        "first": _commit(raw, repo_path, "poem.txt", "one\ntwo\nthree\n", "write the poem"),
        "middle": _commit(raw, repo_path, "poem.txt", "one\nTWO\nthree\n", "shout the middle line"),
        "last": _commit(raw, repo_path, "poem.txt", "one\nTWO\nTHREE\n", "shout the last line"),
    }
    return Pygit2Repository(str(repo_path)), repo_path, oids


# ── Attribution ──────────────────────────────────────────────────────────────


def test_every_line_is_attributed_to_the_commit_that_last_touched_it(blame_repo):
    impl, _, oids = blame_repo
    lines = impl.get_blame("poem.txt")

    assert [line.text for line in lines] == ["one", "TWO", "THREE"]
    assert [line.commit_oid for line in lines] == [oids["first"], oids["middle"], oids["last"]]


def test_line_numbers_are_contiguous_and_one_based(blame_repo):
    impl, _, _ = blame_repo
    lines = impl.get_blame("poem.txt")
    assert [line.line_no for line in lines] == [1, 2, 3]


def test_run_starts_mark_only_the_first_line_of_each_run(blame_repo):
    """Consecutive lines from one commit form a run so a view can label it once."""
    impl, path, _ = blame_repo
    raw = pygit2.Repository(str(path))
    # Rewrite the tail as a single commit: lines 2 and 3 become one run.
    _commit(raw, path, "poem.txt", "one\nTWO AGAIN\nTHREE AGAIN\n", "redo the tail")

    lines = impl.get_blame("poem.txt")
    assert [line.is_run_start for line in lines] == [True, True, False]
    assert lines[1].commit_oid == lines[2].commit_oid


def test_summary_is_the_commits_subject_line(blame_repo):
    impl, _, _ = blame_repo
    lines = impl.get_blame("poem.txt")
    assert lines[0].summary == "write the poem"
    assert lines[2].summary == "shout the last line"


def test_author_is_reported_not_the_committer(blame_repo):
    """Blame reports a committer; a blame view shows the author.

    They differ on anything rebased, cherry-picked, or applied from a patch —
    exactly the commits where getting it wrong misattributes the work.
    """
    impl, path, _ = blame_repo
    raw = pygit2.Repository(str(path))
    _commit(
        raw,
        path,
        "poem.txt",
        "one\nTWO\nFOUR\n",
        "someone else's line",
        author=pygit2.Signature("Original Author", "original@example.com"),
    )

    lines = impl.get_blame("poem.txt")
    assert lines[2].author == "Original Author"
    assert lines[0].author == "Test User"


# ── Revisions ────────────────────────────────────────────────────────────────


def test_at_oid_blames_that_revision_not_head(blame_repo):
    impl, _, oids = blame_repo
    lines = impl.get_blame("poem.txt", at_oid=oids["first"])

    assert [line.text for line in lines] == ["one", "two", "three"]
    assert {line.commit_oid for line in lines} == {oids["first"]}


def test_blame_of_a_file_added_later_fails_at_an_earlier_revision(blame_repo):
    impl, path, oids = blame_repo
    raw = pygit2.Repository(str(path))
    _commit(raw, path, "newcomer.txt", "hello\n", "add newcomer")

    assert impl.get_blame("newcomer.txt")  # exists at HEAD
    with pytest.raises(ValueError, match="does not exist"):
        impl.get_blame("newcomer.txt", at_oid=oids["first"])


# ── Failure modes ────────────────────────────────────────────────────────────


def test_unborn_branch_raises(tmp_path):
    pygit2.init_repository(str(tmp_path))
    impl = Pygit2Repository(str(tmp_path))
    with pytest.raises(ValueError, match="no commits yet"):
        impl.get_blame("anything.txt")


def test_missing_path_raises(blame_repo):
    impl, _, _ = blame_repo
    with pytest.raises(ValueError, match="does not exist"):
        impl.get_blame("never-existed.txt")


def test_binary_file_raises(blame_repo):
    impl, path, _ = blame_repo
    raw = pygit2.Repository(str(path))
    (path / "blob.bin").write_bytes(b"\x00\x01\x02binary\x00content")
    raw.index.add("blob.bin")
    raw.index.write()
    sig = pygit2.Signature("Test User", "test@example.com")
    raw.create_commit("HEAD", sig, sig, "add binary", raw.index.write_tree(), [raw.head.target])

    with pytest.raises(ValueError, match="binary"):
        impl.get_blame("blob.bin")


def test_directory_raises(blame_repo):
    impl, path, _ = blame_repo
    raw = pygit2.Repository(str(path))
    (path / "sub").mkdir()
    (path / "sub" / "f.txt").write_text("x\n")
    raw.index.add("sub/f.txt")
    raw.index.write()
    sig = pygit2.Signature("Test User", "test@example.com")
    raw.create_commit("HEAD", sig, sig, "add sub", raw.index.write_tree(), [raw.head.target])

    with pytest.raises(ValueError, match="Not a file"):
        impl.get_blame("sub")


# ── Agreement with git ───────────────────────────────────────────────────────


@pytest.mark.skipif(shutil.which("git") is None, reason="cross-checks against the git CLI")
def test_attribution_matches_git_blame(blame_repo):
    """Our attribution must be the one users would get from `git blame`."""
    impl, path, _ = blame_repo
    ours = [line.commit_oid for line in impl.get_blame("poem.txt")]

    proc = subprocess.run(
        ["git", "blame", "--porcelain", "poem.txt"],
        cwd=path,
        capture_output=True,
        text=True,
        check=True,
    )
    # A porcelain header line starts each line's record: "<sha> <orig> <final> [n]"
    theirs = [
        ln.split()[0]
        for ln in proc.stdout.splitlines()
        if len(ln.split()) >= 3 and len(ln.split()[0]) == 40 and ln.split()[1].isdigit()
    ]

    assert ours == theirs
