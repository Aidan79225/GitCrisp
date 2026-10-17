"""WorktreeOps mixin — exercised via Pygit2Repository against real repos."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pygit2
import pytest

from git_gui.infrastructure.pygit2 import Pygit2Repository
from git_gui.infrastructure.worktree_cli import WorktreeCommandError, WorktreeDirtyError


@pytest.fixture
def fresh_repo(tmp_path):
    """Empty-ish repo with one commit on master."""
    p = tmp_path / "main"
    p.mkdir()
    repo = pygit2.init_repository(str(p), initial_head="master")
    repo.config["user.name"] = "T"
    repo.config["user.email"] = "t@e.com"
    sig = pygit2.Signature("T", "t@e.com")
    (p / "a.txt").write_text("hi\n")
    repo.index.add("a.txt")
    repo.index.write()
    tree = repo.index.write_tree()
    repo.create_commit("refs/heads/master", sig, sig, "init", tree, [])
    return p


def test_list_worktrees_returns_just_main_when_no_extra(fresh_repo):
    impl = Pygit2Repository(str(fresh_repo))
    wts = impl.list_worktrees()
    assert len(wts) == 1
    main = wts[0]
    assert main.is_main is True
    assert Path(main.path) == Path(str(fresh_repo)).resolve()
    assert main.branch == "master"
    assert main.is_locked is False


def test_list_worktrees_includes_added_worktree(fresh_repo, tmp_path):
    repo = pygit2.Repository(str(fresh_repo))
    repo.references.create("refs/heads/feat", repo.head.target)
    wt_path = tmp_path / "wt-feat"
    subprocess.run(
        ["git", "-C", str(fresh_repo), "worktree", "add", str(wt_path), "feat"],
        check=True,
        capture_output=True,
    )
    impl = Pygit2Repository(str(fresh_repo))
    wts = impl.list_worktrees()
    branches = {wt.branch for wt in wts}
    assert "master" in branches
    assert "feat" in branches
    feat = next(wt for wt in wts if wt.branch == "feat")
    assert feat.is_main is False
    assert Path(feat.path) == wt_path.resolve()


@pytest.fixture
def linked_worktree(fresh_repo, tmp_path):
    """A linked worktree of fresh_repo on branch feat."""
    repo = pygit2.Repository(str(fresh_repo))
    repo.references.create("refs/heads/feat", repo.head.target)
    wt_path = tmp_path / "wt-feat"
    subprocess.run(
        ["git", "-C", str(fresh_repo), "worktree", "add", str(wt_path), "feat"],
        check=True,
        capture_output=True,
    )
    return wt_path


def test_list_worktrees_from_a_linked_worktree_names_the_real_main(fresh_repo, linked_worktree):
    """A session opened on a linked worktree lists the same worktrees as the
    main repo's session.

    It used to take its own directory for the main worktree, so the real main
    repo went missing and the linked worktree was listed twice — once as main
    and once as itself — leaving the repo list nothing to nest it under.
    """
    from_main = Pygit2Repository(str(fresh_repo)).list_worktrees()
    from_linked = Pygit2Repository(str(linked_worktree)).list_worktrees()

    assert [(wt.path, wt.is_main) for wt in from_linked] == [
        (wt.path, wt.is_main) for wt in from_main
    ]
    main = next(wt for wt in from_linked if wt.is_main)
    assert Path(main.path) == fresh_repo.resolve()
    assert main.branch == "master"


def test_lock_state_is_read_from_a_linked_worktree_session(fresh_repo, linked_worktree):
    """The lock sentinel lives under the common git dir, not the linked
    worktree's own git dir."""
    Pygit2Repository(str(fresh_repo)).lock_worktree(str(linked_worktree), reason="testing")

    wts = Pygit2Repository(str(linked_worktree)).list_worktrees()

    feat = next(wt for wt in wts if not wt.is_main)
    assert feat.is_locked is True
    assert feat.lock_reason == "testing"


def test_add_worktree_creates_new_branch_and_directory(fresh_repo, tmp_path):
    impl = Pygit2Repository(str(fresh_repo))
    target = tmp_path / "wt-new"
    wt = impl.add_worktree(
        str(target),
        "feat/new",
        create_branch=True,
        base_ref="master",
    )
    assert target.exists()
    assert wt.branch == "feat/new"
    assert wt.is_main is False
    repo = pygit2.Repository(str(fresh_repo))
    assert "refs/heads/feat/new" in [b for b in repo.references]


def test_add_worktree_attaches_existing_branch(fresh_repo, tmp_path):
    repo = pygit2.Repository(str(fresh_repo))
    repo.references.create("refs/heads/existing", repo.head.target)
    impl = Pygit2Repository(str(fresh_repo))
    target = tmp_path / "wt-existing"
    wt = impl.add_worktree(
        str(target),
        "existing",
        create_branch=False,
        base_ref=None,
    )
    assert wt.branch == "existing"


def test_find_worktree_for_branch_returns_match(fresh_repo, tmp_path):
    repo = pygit2.Repository(str(fresh_repo))
    repo.references.create("refs/heads/feat", repo.head.target)
    subprocess.run(
        ["git", "-C", str(fresh_repo), "worktree", "add", str(tmp_path / "wt-feat"), "feat"],
        check=True,
        capture_output=True,
    )
    impl = Pygit2Repository(str(fresh_repo))
    wt = impl.find_worktree_for_branch("feat")
    assert wt is not None
    assert wt.branch == "feat"


def test_find_worktree_for_branch_returns_none_when_missing(fresh_repo):
    impl = Pygit2Repository(str(fresh_repo))
    assert impl.find_worktree_for_branch("does-not-exist") is None


def test_lock_and_unlock_round_trip(fresh_repo, tmp_path):
    repo = pygit2.Repository(str(fresh_repo))
    repo.references.create("refs/heads/feat", repo.head.target)
    wt_path = tmp_path / "wt-feat"
    subprocess.run(
        ["git", "-C", str(fresh_repo), "worktree", "add", str(wt_path), "feat"],
        check=True,
        capture_output=True,
    )
    impl = Pygit2Repository(str(fresh_repo))
    impl.lock_worktree(str(wt_path), reason="testing")
    wts = impl.list_worktrees()
    feat = next(wt for wt in wts if wt.branch == "feat")
    assert feat.is_locked is True
    assert feat.lock_reason == "testing"

    impl.unlock_worktree(str(wt_path))
    wts = impl.list_worktrees()
    feat = next(wt for wt in wts if wt.branch == "feat")
    assert feat.is_locked is False


def test_remove_worktree_clean(fresh_repo, tmp_path):
    repo = pygit2.Repository(str(fresh_repo))
    repo.references.create("refs/heads/feat", repo.head.target)
    wt_path = tmp_path / "wt-feat"
    subprocess.run(
        ["git", "-C", str(fresh_repo), "worktree", "add", str(wt_path), "feat"],
        check=True,
        capture_output=True,
    )
    impl = Pygit2Repository(str(fresh_repo))
    impl.remove_worktree(str(wt_path), force=False)
    assert not wt_path.exists()


def test_remove_worktree_dirty_without_force_raises(fresh_repo, tmp_path):
    repo = pygit2.Repository(str(fresh_repo))
    repo.references.create("refs/heads/feat", repo.head.target)
    wt_path = tmp_path / "wt-feat"
    subprocess.run(
        ["git", "-C", str(fresh_repo), "worktree", "add", str(wt_path), "feat"],
        check=True,
        capture_output=True,
    )
    (wt_path / "a.txt").write_text("changed\n")
    impl = Pygit2Repository(str(fresh_repo))
    with pytest.raises(WorktreeDirtyError):
        impl.remove_worktree(str(wt_path), force=False)


def test_a_session_can_remove_the_worktree_it_is_open_on(linked_worktree):
    """git ran inside the worktree being removed, and Windows will not delete a
    process's current directory: the files and registration went, the empty
    folder stayed, and the removal was reported as a failure."""
    impl = Pygit2Repository(str(linked_worktree))

    impl.remove_worktree(str(linked_worktree), force=False)

    assert not linked_worktree.exists()


def test_add_worktree_into_an_existing_empty_folder(fresh_repo, tmp_path):
    """Browse… can only pick a folder that already exists, and git accepts an
    empty one; libgit2 refused it with "directory exists"."""
    target = tmp_path / "picked"
    target.mkdir()

    wt = Pygit2Repository(str(fresh_repo)).add_worktree(
        str(target), "picked", create_branch=True, base_ref="master"
    )

    assert wt.branch == "picked"
    assert (target / "a.txt").read_text() == "hi\n"


def test_add_worktrees_whose_folders_share_a_name(fresh_repo, tmp_path):
    """The folder name was used as the worktree's admin name, so a second
    `app` folder anywhere else collided with the first."""
    impl = Pygit2Repository(str(fresh_repo))
    impl.add_worktree(str(tmp_path / "a" / "app"), "one", create_branch=True, base_ref="master")

    impl.add_worktree(str(tmp_path / "b" / "app"), "two", create_branch=True, base_ref="master")

    assert {wt.branch for wt in impl.list_worktrees()} == {"master", "one", "two"}


def test_a_lock_reason_git_wrote_is_read_as_utf8(fresh_repo, linked_worktree):
    """Read in the locale code page (cp950 here), git's UTF-8 reason raised
    UnicodeDecodeError and every worktree vanished from the list."""
    reason = "測試中 Łódź"
    subprocess.run(
        ["git", "worktree", "lock", "--reason", reason, str(linked_worktree)],
        cwd=fresh_repo,
        check=True,
        capture_output=True,
    )

    wts = Pygit2Repository(str(fresh_repo)).list_worktrees()

    assert next(wt for wt in wts if not wt.is_main).lock_reason == reason


def test_a_lock_reason_is_written_as_utf8(fresh_repo, linked_worktree):
    """git reads the reason as UTF-8; the locale code page gave it mojibake,
    or raised after the lock was already taken for a character it lacks."""
    reason = "🔒 Łódź 測試中"

    Pygit2Repository(str(fresh_repo)).lock_worktree(str(linked_worktree), reason=reason)

    locked = fresh_repo / ".git" / "worktrees" / linked_worktree.name / "locked"
    assert locked.read_bytes() == reason.encode("utf-8")


def test_a_new_branch_starts_at_the_base_branch_not_a_same_named_tag(fresh_repo, tmp_path):
    """revparse prefers refs/tags/<name> over refs/heads/<name>, and the tag
    object was not peeled: the branch started at the tag's commit and its ref
    held a tag object, which `git fsck` reports as an error."""
    repo = pygit2.Repository(str(fresh_repo))
    branch_tip = repo.head.target
    repo.references.create("refs/heads/rel", branch_tip)
    sig = pygit2.Signature("T", "t@e.com")
    later = repo.create_commit(
        "refs/heads/master", sig, sig, "later", repo.head.peel(pygit2.Tree).id, [branch_tip]
    )
    repo.create_tag("rel", later, pygit2.enums.ObjectType.COMMIT, sig, "release")

    Pygit2Repository(str(fresh_repo)).add_worktree(
        str(tmp_path / "wt-rel"), "from-rel", create_branch=True, base_ref="rel"
    )

    assert repo.references["refs/heads/from-rel"].target == branch_tip


def test_a_failed_add_does_not_leave_the_new_branch_behind(fresh_repo, tmp_path):
    """The branch was created before the worktree, so a refused target left it
    behind and retrying the same name failed with "reference already exists"."""
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep.txt").write_text("mine\n")
    impl = Pygit2Repository(str(fresh_repo))

    with pytest.raises(WorktreeCommandError):
        impl.add_worktree(str(occupied), "newfeat", create_branch=True, base_ref="master")

    assert "newfeat" not in pygit2.Repository(str(fresh_repo)).branches.local


def test_a_failing_post_checkout_hook_keeps_the_worktree_s_branch(fresh_repo, tmp_path):
    """git keeps the worktree when only its post-checkout hook fails, yet
    still exits non-zero; deleting the branch then would strand it."""
    hook = fresh_repo / ".git" / "hooks" / "post-checkout"
    hook.write_text("#!/bin/sh\nexit 1\n", newline="\n")
    hook.chmod(0o755)
    target = tmp_path / "wt-hooked"

    with pytest.raises(WorktreeCommandError):
        Pygit2Repository(str(fresh_repo)).add_worktree(
            str(target), "hooked", create_branch=True, base_ref="master"
        )

    assert (target / "a.txt").exists()
    assert "hooked" in pygit2.Repository(str(fresh_repo)).branches.local


def test_a_worktree_is_added_to_the_open_repo_whatever_git_dir_the_app_inherited(
    fresh_repo, tmp_path, monkeypatch
):
    """Started with GIT_DIR set (from inside a git hook, say), git ranked it
    above the folder it ran in and added the worktree to that other repo."""
    other = tmp_path / "other"
    pygit2.init_repository(str(other))
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))

    wt = Pygit2Repository(str(fresh_repo)).add_worktree(
        str(tmp_path / "wt-inherited"), "inherited", create_branch=True, base_ref="master"
    )

    assert wt.branch == "inherited"


@pytest.fixture
def locked_dirty_worktree(fresh_repo, linked_worktree):
    """linked_worktree locked "on usb", with a modified and an untracked file."""
    subprocess.run(
        ["git", "worktree", "lock", "--reason", "on usb", str(linked_worktree)],
        cwd=fresh_repo,
        check=True,
        capture_output=True,
    )
    (linked_worktree / "a.txt").write_text("changed\n")
    (linked_worktree / "new.txt").write_text("untracked\n")
    return linked_worktree


def _lock_reason(repo_path, worktree):
    wt = next(w for w in Pygit2Repository(str(repo_path)).list_worktrees() if not w.is_main)
    assert Path(wt.path) == worktree.resolve()
    return wt.lock_reason if wt.is_locked else None


def test_force_alone_does_not_remove_a_locked_worktree(fresh_repo, locked_dirty_worktree):
    """force answers the uncommitted-changes prompt only; it passed git's
    lock override too, so the lock prompt's Force remove deleted the changes."""
    from git_gui.infrastructure.worktree_cli import WorktreeLockedError

    with pytest.raises(WorktreeLockedError):
        Pygit2Repository(str(fresh_repo)).remove_worktree(str(locked_dirty_worktree), force=True)

    assert (locked_dirty_worktree / "new.txt").exists()


def test_overriding_a_lock_still_refuses_uncommitted_changes(fresh_repo, locked_dirty_worktree):
    """git cannot skip its lock check without skipping its changes check, so
    the override lifts the lock for a plain remove and puts it back after."""
    impl = Pygit2Repository(str(fresh_repo))

    with pytest.raises(WorktreeDirtyError):
        impl.remove_worktree(str(locked_dirty_worktree), force=False, override_lock=True)

    assert (locked_dirty_worktree / "new.txt").exists()
    assert _lock_reason(fresh_repo, locked_dirty_worktree) == "on usb"


def test_overriding_a_lock_and_forcing_removes_a_dirty_worktree(fresh_repo, locked_dirty_worktree):
    Pygit2Repository(str(fresh_repo)).remove_worktree(
        str(locked_dirty_worktree), force=True, override_lock=True
    )

    assert not locked_dirty_worktree.exists()


def test_overriding_a_lock_removes_a_clean_worktree(fresh_repo, linked_worktree):
    impl = Pygit2Repository(str(fresh_repo))
    impl.lock_worktree(str(linked_worktree))

    impl.remove_worktree(str(linked_worktree), force=False, override_lock=True)

    assert not linked_worktree.exists()
