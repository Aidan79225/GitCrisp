"""Regression tests for Pygit2Repository.is_dirty().

is_dirty() runs on every auto-reload (via the graph reload worker). If its
`git status` call refreshes/rewrites .git/index as a side effect, that write
trips the RepoChangeDetector's file watcher and schedules yet another reload —
a self-perpetuating loop that makes the commit-detail pane jump every few
seconds. Passing GIT_OPTIONAL_LOCKS=0 stops git from touching the index.
"""

from __future__ import annotations

import subprocess

from git_gui.infrastructure.pygit2 import Pygit2Repository


def test_is_dirty_false_on_clean_repo(repo_impl):
    assert repo_impl.is_dirty() is False


def test_is_dirty_true_with_untracked_file(repo_path):
    (repo_path / "new.txt").write_text("x")
    impl = Pygit2Repository(str(repo_path))
    assert impl.is_dirty() is True


def test_is_dirty_passes_optional_locks_off(repo_impl, monkeypatch):
    """The git status call must set GIT_OPTIONAL_LOCKS=0 so it doesn't
    rewrite .git/index and re-trigger the change detector."""
    captured: dict = {}
    real_run = subprocess.run

    def _spy(cmd, *args, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _spy)
    repo_impl.is_dirty()

    assert captured["cmd"][:3] == ["git", "status", "--porcelain"]
    assert captured["env"] is not None
    assert captured["env"].get("GIT_OPTIONAL_LOCKS") == "0"


def test_is_dirty_does_not_rewrite_index(repo_path):
    """Two consecutive dirty checks on a clean repo must not keep rewriting
    .git/index — the mtime should be stable after the first refresh."""
    impl = Pygit2Repository(str(repo_path))
    index_path = repo_path / ".git" / "index"

    impl.is_dirty()  # warm any first-time refresh
    before = index_path.stat().st_mtime_ns
    impl.is_dirty()
    after = index_path.stat().st_mtime_ns

    assert before == after
