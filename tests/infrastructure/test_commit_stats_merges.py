"""What Insight counts, and what a merge commit would have added to it.

A merge introduces no changes of its own — `git log --numstat` prints nothing
underneath one — so counting it raises every commit total with no lines to
account for it, and credits whoever pressed the button rather than whoever
wrote the code. On a history that lands work through pull requests that is not
a rounding error: one merge per branch can be a third of the commits.
"""

from __future__ import annotations

import subprocess

import pygit2
import pytest

from git_gui.infrastructure.pygit2 import Pygit2Repository

WRITER = pygit2.Signature("Writer", "writer@example.com", 1000, 0)
MERGER = pygit2.Signature("Merger", "merger@example.com", 2000, 0)


def _commit(repo, workdir, files, message, parents, ref, author):
    """Commit *files* on top of *parents* — the first parent supplies the tree."""
    if parents:
        repo.index.read_tree(repo.get(parents[0]).tree)
    else:
        repo.index.clear()
    for name, content in files.items():
        (workdir / name).write_text(content)
        repo.index.add(name)
    repo.index.write()
    tree = repo.index.write_tree()
    return str(repo.create_commit(ref, author, author, message, tree, list(parents)))


@pytest.fixture
def merged_history(repo_path):
    """A branch of one commit, merged back into master by a different person."""
    repo = pygit2.Repository(str(repo_path))
    base = str(repo.head.target)

    feature = _commit(
        repo,
        repo_path,
        {"feature.py": "one\ntwo\nthree\n"},
        "add the feature",
        [base],
        "refs/heads/feature",
        WRITER,
    )
    merge = _commit(
        repo,
        repo_path,
        {"feature.py": "one\ntwo\nthree\n"},
        "Merge pull request #1",
        [base, feature],
        "refs/heads/master",
        MERGER,
    )
    repo.set_head("refs/heads/master")
    return Pygit2Repository(str(repo_path)), base, feature, merge


def _stats(impl):
    return list(impl.get_commit_stats())


# ── The merge itself ─────────────────────────────────────────────────────────


def test_a_merge_commit_is_not_counted(merged_history):
    impl, _base, _feature, merge = merged_history

    assert merge not in {cs.oid for cs in _stats(impl)}


def test_a_merge_would_have_arrived_with_no_lines_at_all(merged_history):
    """The reason it is excluded rather than counted rather than fixed.

    `git log --numstat` prints no file lines under a merge — unlike `git show`,
    which falls back to a combined diff — so a counted merge could only ever
    have been a commit with an empty bar beside it.
    """
    impl, _base, _feature, merge = merged_history

    out = subprocess.run(
        ["git", "log", "-1", "--numstat", "--format=", merge],
        cwd=str(impl._repo.workdir),
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert out.strip() == ""


def test_the_person_who_only_merged_gets_no_commit(merged_history):
    """The distortion that made this worth fixing: a reviewer who never wrote a
    line ranks in Top Authors, with an empty bar beside the count."""
    impl, *_ = merged_history

    assert "Merger <merger@example.com>" not in {cs.author for cs in _stats(impl)}


# ── What must survive it ─────────────────────────────────────────────────────


def test_the_work_the_merge_brought_in_is_still_counted(merged_history):
    """Excluding the merge must not exclude the branch under it — that would
    lose the very commits the merge was there to deliver."""
    impl, _base, feature, _merge = merged_history

    by_oid = {cs.oid: cs for cs in _stats(impl)}

    assert feature in by_oid
    assert by_oid[feature].author == "Writer <writer@example.com>"
    assert [(f.path, f.added, f.deleted) for f in by_oid[feature].files] == [("feature.py", 3, 0)]


def test_ordinary_commits_are_untouched(merged_history):
    impl, base, _feature, _merge = merged_history

    assert base in {cs.oid for cs in _stats(impl)}


def test_a_history_with_no_merges_counts_every_commit(repo_path):
    """The common case must not pay for the fix."""
    repo = pygit2.Repository(str(repo_path))
    parent = str(repo.head.target)
    made = [parent]
    for i in range(3):
        parent = _commit(
            repo,
            repo_path,
            {f"f{i}.txt": "x\n"},
            f"c{i}",
            [parent],
            "refs/heads/master",
            WRITER,
        )
        made.append(parent)

    impl = Pygit2Repository(str(repo_path))

    assert {cs.oid for cs in _stats(impl)} == set(made)
