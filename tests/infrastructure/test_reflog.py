"""Tests for reading a ref's reflog — the record that makes undo possible."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pygit2
import pytest

from git_gui.infrastructure.pygit2 import Pygit2Repository
from git_gui.infrastructure.pygit2.reflog_ops import _split_message

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="builds reflog states with the git CLI"
)


def _git(path: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@e.com", "-c", "user.name=T", *args],
        cwd=path,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def moved_repo(repo_path: Path) -> tuple[Pygit2Repository, Path, str]:
    """A repo whose HEAD has been moved by a commit, a branch switch and a reset."""
    (repo_path / "a.txt").write_text("one\n")
    _git(repo_path, "add", ".")
    _git(repo_path, "commit", "-qm", "add a")
    before_reset = str(pygit2.Repository(str(repo_path)).head.target)

    (repo_path / "a.txt").write_text("two\n")
    _git(repo_path, "add", ".")
    _git(repo_path, "commit", "-qm", "change a")
    _git(repo_path, "reset", "--hard", before_reset)

    return Pygit2Repository(str(repo_path)), repo_path, before_reset


# ── Reading ──────────────────────────────────────────────────────────────────


def test_entries_are_newest_first_and_indexed_like_head_at_n(moved_repo):
    impl, _, _ = moved_repo
    entries = impl.get_reflog()

    assert [e.index for e in entries] == list(range(len(entries)))
    assert entries[0].operation == "reset", "the reset was the most recent move"


def test_each_entry_records_where_the_ref_came_from_and_went_to(moved_repo):
    impl, _, before_reset = moved_repo
    reset_entry = impl.get_reflog()[0]

    assert reset_entry.oid_new == before_reset
    assert reset_entry.oid_old != reset_entry.oid_new, "the reset actually moved HEAD"


def test_the_operation_is_split_from_the_rest_of_the_message(moved_repo):
    impl, _, _ = moved_repo
    operations = [e.operation for e in impl.get_reflog()]

    assert "commit" in operations
    assert "reset" in operations
    # The detail must not be swallowed into the operation column.
    assert all(":" not in op for op in operations if op)


def test_the_ref_creation_entry_has_no_previous_state(moved_repo):
    """The oldest entry's `oid_old` is the null oid — there was nothing before.

    Reported as None so a caller cannot offer to restore to forty zeroes.
    """
    impl, _, _ = moved_repo
    oldest = impl.get_reflog()[-1]

    assert oldest.oid_old is None
    assert all(e.oid_old is not None for e in impl.get_reflog()[:-1])


def test_limit_takes_the_most_recent_entries(moved_repo):
    impl, _, _ = moved_repo
    full = impl.get_reflog()
    assert len(full) > 2

    limited = impl.get_reflog(limit=2)
    assert [e.oid_new for e in limited] == [e.oid_new for e in full[:2]]


def test_head_reflog_is_the_fuller_record(moved_repo):
    """HEAD records branch switches that a branch's own reflog does not."""
    impl, path, _ = moved_repo
    _git(path, "checkout", "-q", "-b", "side")
    _git(path, "checkout", "-q", "master")

    assert len(impl.get_reflog("HEAD")) > len(impl.get_reflog("refs/heads/master"))


def test_committer_and_timestamp_come_through(moved_repo):
    impl, _, _ = moved_repo
    entry = impl.get_reflog()[0]

    assert entry.committer == "T"
    assert entry.timestamp.year >= 2020


def test_unknown_ref_raises(moved_repo):
    impl, _, _ = moved_repo
    with pytest.raises(ValueError, match="No such ref"):
        impl.get_reflog("refs/heads/never-existed")


# ── Message parsing ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("commit: add a thing", ("commit", "add a thing")),
        # A qualifier says what actually happened, so it stays with the operation.
        ("commit (amend): reword", ("commit (amend)", "reword")),
        (
            "rebase (finish): returning to refs/heads/main",
            ("rebase (finish)", "returning to refs/heads/main"),
        ),
        ("checkout: moving from a to b", ("checkout", "moving from a to b")),
        # Not every writer follows the convention; keep the text rather than
        # dropping it into a column it does not belong in.
        ("no separator here", ("", "no separator here")),
        (None, ("", "")),
        ("", ("", "")),
    ],
)
def test_message_split(message, expected):
    assert _split_message(message) == expected


# ── Orphaned entries ─────────────────────────────────────────────────────────


def test_a_commit_no_ref_reaches_is_marked_orphaned(repo_path: Path):
    """The reflog is the only way back to these, which is why they matter."""
    _git(repo_path, "checkout", "-q", "-b", "doomed")
    (repo_path / "gone.txt").write_text("only on this branch\n")
    _git(repo_path, "add", ".")
    _git(repo_path, "commit", "-qm", "will be orphaned")
    orphan = str(pygit2.Repository(str(repo_path)).head.target)
    _git(repo_path, "checkout", "-q", "master")
    _git(repo_path, "branch", "-D", "doomed")

    entries = Pygit2Repository(str(repo_path)).get_reflog()
    by_oid = {e.oid_new: e for e in entries}

    assert by_oid[orphan].is_orphaned, "nothing points at it any more"


def test_commits_a_branch_still_reaches_are_not_orphaned(repo_path: Path):
    (repo_path / "kept.txt").write_text("reachable\n")
    _git(repo_path, "add", ".")
    _git(repo_path, "commit", "-qm", "still on master")
    kept = str(pygit2.Repository(str(repo_path)).head.target)

    entries = Pygit2Repository(str(repo_path)).get_reflog()
    by_oid = {e.oid_new: e for e in entries}

    assert not by_oid[kept].is_orphaned


def test_a_commit_only_a_tag_reaches_is_not_orphaned(repo_path: Path):
    """A tag is a ref too — the reflog is not the last resort here."""
    _git(repo_path, "checkout", "-q", "-b", "tagged")
    (repo_path / "t.txt").write_text("tagged\n")
    _git(repo_path, "add", ".")
    _git(repo_path, "commit", "-qm", "will be tagged")
    oid = str(pygit2.Repository(str(repo_path)).head.target)
    _git(repo_path, "tag", "keep-me")
    _git(repo_path, "checkout", "-q", "master")
    _git(repo_path, "branch", "-D", "tagged")

    entries = Pygit2Repository(str(repo_path)).get_reflog()
    assert not {e.oid_new: e for e in entries}[oid].is_orphaned


def test_a_reset_leaves_the_commits_it_dropped_orphaned(repo_path: Path):
    """The recovery case: reset --hard, and the reflog is all that is left."""
    (repo_path / "a.txt").write_text("keep\n")
    _git(repo_path, "add", ".")
    _git(repo_path, "commit", "-qm", "keep")
    base = str(pygit2.Repository(str(repo_path)).head.target)
    (repo_path / "a.txt").write_text("lose\n")
    _git(repo_path, "add", ".")
    _git(repo_path, "commit", "-qm", "about to be dropped")
    dropped = str(pygit2.Repository(str(repo_path)).head.target)
    _git(repo_path, "reset", "--hard", base)

    entries = Pygit2Repository(str(repo_path)).get_reflog()
    by_oid = {e.oid_new: e for e in entries}

    assert by_oid[dropped].is_orphaned
    assert not by_oid[base].is_orphaned
