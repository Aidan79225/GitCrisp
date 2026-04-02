import pygit2
import pytest
from pathlib import Path
from git_gui.infrastructure.pygit2_repo import Pygit2Repository


@pytest.fixture
def writable_repo(repo_path) -> tuple[Pygit2Repository, Path]:
    return Pygit2Repository(str(repo_path)), repo_path


def test_stage_adds_new_file(writable_repo):
    impl, path = writable_repo
    (path / "new.txt").write_text("hello\n")
    impl.stage(["new.txt"])
    raw = pygit2.Repository(str(path))
    assert raw.status_file("new.txt") == pygit2.GIT_STATUS_INDEX_NEW


def test_unstage_removes_file_from_index(writable_repo):
    impl, path = writable_repo
    (path / "staged.txt").write_text("data\n")
    impl.stage(["staged.txt"])
    impl.unstage(["staged.txt"])
    raw = pygit2.Repository(str(path))
    assert raw.status_file("staged.txt") & pygit2.GIT_STATUS_WT_NEW


def test_commit_creates_new_commit(writable_repo):
    impl, path = writable_repo
    (path / "c.txt").write_text("content\n")
    impl.stage(["c.txt"])
    commit = impl.commit("feat: add c.txt")
    assert commit.message == "feat: add c.txt"
    raw = pygit2.Repository(str(path))
    assert str(raw.head.target) == commit.oid


def test_create_branch(writable_repo):
    impl, path = writable_repo
    commits = impl.get_commits(limit=1)
    branch = impl.create_branch("feature/x", commits[0].oid)
    assert branch.name == "feature/x"
    raw = pygit2.Repository(str(path))
    assert raw.branches.local["feature/x"] is not None


def test_checkout_switches_branch(writable_repo):
    impl, path = writable_repo
    commits = impl.get_commits(limit=1)
    impl.create_branch("feature/y", commits[0].oid)
    impl.checkout("feature/y")
    raw = pygit2.Repository(str(path))
    assert raw.head.shorthand == "feature/y"


def test_delete_branch(writable_repo):
    impl, path = writable_repo
    commits = impl.get_commits(limit=1)
    impl.create_branch("to-delete", commits[0].oid)
    impl.delete_branch("to-delete")
    raw = pygit2.Repository(str(path))
    assert "to-delete" not in list(raw.branches.local)


def test_stash_and_pop(writable_repo):
    impl, path = writable_repo
    (path / "README.md").write_text("modified\n")
    impl.stash("WIP: test stash")
    stashes = impl.get_stashes()
    assert len(stashes) == 1
    assert "WIP: test stash" in stashes[0].message
    impl.pop_stash(0)
    stashes_after = impl.get_stashes()
    assert len(stashes_after) == 0
