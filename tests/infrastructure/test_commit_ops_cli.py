from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from git_gui.domain.entities import RepoState
from git_gui.infrastructure.commit_ops_cli import CommitOpsCli, CommitOpsCommandError
from git_gui.infrastructure.pygit2 import Pygit2Repository


def _run(cwd: str, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=cwd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


def _commit(cwd: Path, filename: str, content: str, msg: str) -> str:
    (cwd / filename).write_text(content)
    _run(str(cwd), "add", "-A")
    _run(str(cwd), "commit", "-m", msg)
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )
    return r.stdout.strip()


@pytest.fixture
def linear_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """master with 3 commits. Returns (path, base_sha, tip_sha)."""
    _run(str(tmp_path), "init", "-q", "-b", "master")
    _run(str(tmp_path), "config", "user.email", "t@t")
    _run(str(tmp_path), "config", "user.name", "t")
    base = _commit(tmp_path, "a.txt", "a\n", "add a")
    _commit(tmp_path, "b.txt", "b\n", "add b")
    tip = _commit(tmp_path, "c.txt", "c\n", "add c")
    return tmp_path, base, tip


def test_cherry_pick_non_merge_applies_commit_to_head(linear_repo, tmp_path):
    repo_path, _base, _tip = linear_repo
    # Create a branch off base, cherry-pick the tip onto it.
    _run(str(repo_path), "checkout", "-q", "-b", "feature", _base)
    # Cherry-pick: pick the top-of-master commit onto feature.
    # First we need a non-conflicting commit — use the tip which adds c.txt.
    tip_on_master = subprocess.run(
        ["git", "rev-parse", "master"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    cli = CommitOpsCli(str(repo_path))
    cli.cherry_pick(tip_on_master, is_merge=False)

    assert (repo_path / "c.txt").exists()
    # HEAD is now a new commit on feature, not tip_on_master itself.
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert head != tip_on_master


def test_cherry_pick_invalid_sha_raises(linear_repo):
    repo_path, _base, _tip = linear_repo
    cli = CommitOpsCli(str(repo_path))
    with pytest.raises(RuntimeError):
        cli.cherry_pick("0000000000000000000000000000000000000000", is_merge=False)


def test_cherry_pick_conflict_does_not_raise(tmp_path: Path):
    """A cherry-pick that conflicts leaves state on disk; the CLI must not raise."""
    _run(str(tmp_path), "init", "-q", "-b", "master")
    _run(str(tmp_path), "config", "user.email", "t@t")
    _run(str(tmp_path), "config", "user.name", "t")
    _commit(tmp_path, "f.txt", "line1\n", "init")
    _run(str(tmp_path), "checkout", "-q", "-b", "a")
    conflict_sha = _commit(tmp_path, "f.txt", "from-a\n", "from a")
    _run(str(tmp_path), "checkout", "-q", "master")
    _commit(tmp_path, "f.txt", "from-master\n", "from master")

    cli = CommitOpsCli(str(tmp_path))
    cli.cherry_pick(conflict_sha, is_merge=False)  # Must not raise.
    assert (tmp_path / ".git" / "CHERRY_PICK_HEAD").exists()


def test_cherry_pick_merge_commit_with_is_merge_true(tmp_path: Path):
    """Cherry-picking a merge commit requires -m; is_merge=True passes it."""
    _run(str(tmp_path), "init", "-q", "-b", "master")
    _run(str(tmp_path), "config", "user.email", "t@t")
    _run(str(tmp_path), "config", "user.name", "t")
    _commit(tmp_path, "base.txt", "base\n", "base")
    _run(str(tmp_path), "checkout", "-q", "-b", "feature")
    _commit(tmp_path, "feat.txt", "feat\n", "feat")
    _run(str(tmp_path), "checkout", "-q", "master")
    _commit(tmp_path, "other.txt", "other\n", "other")
    # Create a merge commit on master.
    _run(str(tmp_path), "merge", "--no-ff", "-m", "merge feature", "feature")
    merge_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    # Now reset master to before the merge and cherry-pick the merge commit.
    _run(str(tmp_path), "reset", "--hard", "HEAD~1")
    # Create a new branch that doesn't have the merge commit yet.
    _run(str(tmp_path), "checkout", "-q", "-b", "target")

    cli = CommitOpsCli(str(tmp_path))
    cli.cherry_pick(merge_sha, is_merge=True)  # Must succeed with -m 1.

    assert (
        tmp_path / "feat.txt"
    ).exists()  # With mainline=1, the cherry-pick replays changes introduced by the feature side, so feat.txt should appear.


def test_revert_commit_non_merge(linear_repo):
    repo_path, _base, tip = linear_repo
    cli = CommitOpsCli(str(repo_path))
    cli.revert_commit(tip, is_merge=False)
    assert not (repo_path / "c.txt").exists()  # the file added in `tip` is removed by the revert


def test_revert_commit_conflict_does_not_raise(tmp_path: Path):
    _run(str(tmp_path), "init", "-q", "-b", "master")
    _run(str(tmp_path), "config", "user.email", "t@t")
    _run(str(tmp_path), "config", "user.name", "t")
    _commit(tmp_path, "f.txt", "line1\n", "init")
    target = _commit(tmp_path, "f.txt", "line2\n", "update")
    _commit(tmp_path, "f.txt", "line3\n", "second update")

    cli = CommitOpsCli(str(tmp_path))
    cli.revert_commit(target, is_merge=False)  # Conflict; must not raise.
    assert (tmp_path / ".git" / "REVERT_HEAD").exists()


def test_cherry_pick_abort(tmp_path: Path):
    _run(str(tmp_path), "init", "-q", "-b", "master")
    _run(str(tmp_path), "config", "user.email", "t@t")
    _run(str(tmp_path), "config", "user.name", "t")
    _commit(tmp_path, "f.txt", "line1\n", "init")
    _run(str(tmp_path), "checkout", "-q", "-b", "a")
    conflict_sha = _commit(tmp_path, "f.txt", "from-a\n", "from a")
    _run(str(tmp_path), "checkout", "-q", "master")
    _commit(tmp_path, "f.txt", "from-master\n", "from master")

    cli = CommitOpsCli(str(tmp_path))
    cli.cherry_pick(conflict_sha, is_merge=False)
    assert (tmp_path / ".git" / "CHERRY_PICK_HEAD").exists()
    cli.cherry_pick_abort()
    assert not (tmp_path / ".git" / "CHERRY_PICK_HEAD").exists()


def test_revert_abort(tmp_path: Path):
    _run(str(tmp_path), "init", "-q", "-b", "master")
    _run(str(tmp_path), "config", "user.email", "t@t")
    _run(str(tmp_path), "config", "user.name", "t")
    _commit(tmp_path, "f.txt", "line1\n", "init")
    target = _commit(tmp_path, "f.txt", "line2\n", "update")
    _commit(tmp_path, "f.txt", "line3\n", "second update")

    cli = CommitOpsCli(str(tmp_path))
    cli.revert_commit(target, is_merge=False)
    assert (tmp_path / ".git" / "REVERT_HEAD").exists()
    cli.revert_abort()
    assert not (tmp_path / ".git" / "REVERT_HEAD").exists()


def test_cherry_pick_continue_after_resolution(tmp_path: Path):
    _run(str(tmp_path), "init", "-q", "-b", "master")
    _run(str(tmp_path), "config", "user.email", "t@t")
    _run(str(tmp_path), "config", "user.name", "t")
    _commit(tmp_path, "f.txt", "line1\n", "init")
    _run(str(tmp_path), "checkout", "-q", "-b", "a")
    conflict_sha = _commit(tmp_path, "f.txt", "from-a\n", "from a")
    _run(str(tmp_path), "checkout", "-q", "master")
    _commit(tmp_path, "f.txt", "from-master\n", "from master")

    cli = CommitOpsCli(str(tmp_path))
    cli.cherry_pick(conflict_sha, is_merge=False)
    # Resolve by taking theirs.
    (tmp_path / "f.txt").write_text("from-a\n")
    _run(str(tmp_path), "add", "f.txt")
    cli.cherry_pick_continue()
    assert not (tmp_path / ".git" / "CHERRY_PICK_HEAD").exists()


def test_revert_continue_after_resolution(tmp_path: Path):
    _run(str(tmp_path), "init", "-q", "-b", "master")
    _run(str(tmp_path), "config", "user.email", "t@t")
    _run(str(tmp_path), "config", "user.name", "t")
    _commit(tmp_path, "f.txt", "line1\n", "init")
    target = _commit(tmp_path, "f.txt", "line2\n", "update")
    _commit(tmp_path, "f.txt", "line3\n", "second update")

    cli = CommitOpsCli(str(tmp_path))
    cli.revert_commit(target, is_merge=False)
    (tmp_path / "f.txt").write_text("resolved\n")
    _run(str(tmp_path), "add", "f.txt")
    cli.revert_continue()
    assert not (tmp_path / ".git" / "REVERT_HEAD").exists()


def test_missing_git_executable_raises_command_error(tmp_path: Path):
    cli = CommitOpsCli(str(tmp_path), git_executable="nonexistent-git-xyz-123")
    with pytest.raises(CommitOpsCommandError):
        cli.cherry_pick("0" * 40, is_merge=False)


def test_cherry_pick_merge_commit_with_is_merge_false_raises(tmp_path: Path):
    """Passing is_merge=False for a real merge commit must raise (no state file written)."""
    _run(str(tmp_path), "init", "-q", "-b", "master")
    _run(str(tmp_path), "config", "user.email", "t@t")
    _run(str(tmp_path), "config", "user.name", "t")
    _commit(tmp_path, "base.txt", "base\n", "base")
    _run(str(tmp_path), "checkout", "-q", "-b", "feature")
    _commit(tmp_path, "feat.txt", "feat\n", "feat")
    _run(str(tmp_path), "checkout", "-q", "master")
    _commit(tmp_path, "other.txt", "other\n", "other")
    _run(str(tmp_path), "merge", "--no-ff", "-m", "merge feature", "feature")
    merge_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    _run(str(tmp_path), "reset", "--hard", "HEAD~1")
    _run(str(tmp_path), "checkout", "-q", "-b", "target")

    cli = CommitOpsCli(str(tmp_path))
    with pytest.raises(RuntimeError):
        cli.cherry_pick(merge_sha, is_merge=False)
    assert not (tmp_path / ".git" / "CHERRY_PICK_HEAD").exists()


@pytest.fixture
def linked_worktree(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    """A linked worktree on master, with commits that conflict when picked or reverted there.

    Returns (worktree, its gitdir, oids). In a linked worktree `.git` is a file
    and git keeps CHERRY_PICK_HEAD / REVERT_HEAD in the gitdir it points to.
    """
    main = tmp_path / "main"
    main.mkdir()
    _run(str(main), "init", "-q", "-b", "master")
    _run(str(main), "config", "user.email", "t@t")
    _run(str(main), "config", "user.name", "t")
    _commit(main, "f.txt", "line1\n", "init")
    _run(str(main), "checkout", "-q", "-b", "a")
    oids = {"from_a": _commit(main, "f.txt", "from-a\n", "from a")}
    _run(str(main), "checkout", "-q", "master")
    oids["update"] = _commit(main, "f.txt", "line2\n", "update")
    _commit(main, "f.txt", "line3\n", "second update")

    worktree = tmp_path / "wt"
    _run(str(main), "worktree", "add", "-b", "wt", str(worktree), "master")
    git_dir = subprocess.run(
        ["git", "rev-parse", "--absolute-git-dir"],
        cwd=str(worktree),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return worktree, Path(git_dir), oids


def test_cherry_pick_conflict_in_a_linked_worktree_does_not_raise(linked_worktree):
    worktree, git_dir, oids = linked_worktree
    cli = CommitOpsCli(str(worktree), git_dir=str(git_dir))

    cli.cherry_pick(oids["from_a"], is_merge=False)  # Conflict; must not raise.

    assert (git_dir / "CHERRY_PICK_HEAD").exists()


def test_revert_conflict_in_a_linked_worktree_does_not_raise(linked_worktree):
    worktree, git_dir, oids = linked_worktree
    cli = CommitOpsCli(str(worktree), git_dir=str(git_dir))

    cli.revert_commit(oids["update"], is_merge=False)  # Conflict; must not raise.

    assert (git_dir / "REVERT_HEAD").exists()


def test_a_failure_naming_a_non_ascii_file_keeps_git_s_message(tmp_path: Path):
    """git writes UTF-8 whatever the locale; decoding it as cp950 lost the whole message."""
    _run(str(tmp_path), "init", "-q", "-b", "master")
    _run(str(tmp_path), "config", "user.email", "t@t")
    _run(str(tmp_path), "config", "user.name", "t")
    _commit(tmp_path, "f.txt", "base\n", "init")
    _run(str(tmp_path), "checkout", "-q", "-b", "a")
    adds_file = _commit(tmp_path, "中文.txt", "tracked\n", "新增中文檔案")
    _run(str(tmp_path), "checkout", "-q", "master")
    (tmp_path / "中文.txt").write_text("untracked\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="中文"):
        CommitOpsCli(str(tmp_path)).cherry_pick(adds_file, is_merge=False)


def test_the_repository_leaves_a_linked_worktree_s_cherry_pick_conflict_in_progress(
    linked_worktree,
):
    worktree, _git_dir, oids = linked_worktree
    repo = Pygit2Repository(str(worktree))

    repo.cherry_pick(oids["from_a"])  # Conflict; must not raise.

    assert repo.repo_state().state is RepoState.CHERRY_PICKING


def test_a_cherry_pick_git_refuses_raises_the_command_error(linear_repo):
    repo_path, _base, _tip = linear_repo

    with pytest.raises(CommitOpsCommandError):
        CommitOpsCli(str(repo_path)).cherry_pick("0" * 40, is_merge=False)
