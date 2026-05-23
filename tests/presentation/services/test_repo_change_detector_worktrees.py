"""RepoChangeDetector should watch .git/worktrees/ for external worktree
add/remove/prune operations."""
from __future__ import annotations
import subprocess

import pygit2
import pytest

from git_gui.presentation.services.repo_change_detector import RepoChangeDetector


@pytest.fixture
def repo(tmp_path):
    p = tmp_path / "r"
    repo = pygit2.init_repository(str(p))
    repo.config["user.name"] = "T"
    repo.config["user.email"] = "t@e.com"
    sig = pygit2.Signature("T", "t@e.com")
    (p / "a.txt").write_text("x")
    repo.index.add("a.txt")
    repo.index.write()
    tree = repo.index.write_tree()
    repo.create_commit("refs/heads/master", sig, sig, "init", tree, [])
    (p / ".git" / "worktrees").mkdir(exist_ok=True)
    return p


def test_worktrees_dir_is_in_watch_set(qtbot, repo):
    d = RepoChangeDetector(str(repo), on_reload=lambda: None)
    try:
        watched = set(d._watcher.directories())
        assert str(repo / ".git" / "worktrees") in watched
    finally:
        d.stop()


def test_external_worktree_add_triggers_reload(qtbot, repo, tmp_path):
    calls: list[None] = []
    d = RepoChangeDetector(str(repo), on_reload=lambda: calls.append(None))
    try:
        gitrepo = pygit2.Repository(str(repo))
        gitrepo.references.create("refs/heads/feat", gitrepo.head.target)
        wt_path = tmp_path / "wt-feat"
        # On macOS, QFileSystemWatcher.directoryChanged can take ~500 ms to
        # arrive (kqueue/FSEvents latency).  Use waitSignal so we block until
        # the OS event is actually delivered rather than relying on a fixed
        # sleep that may be shorter than the platform latency.
        with qtbot.waitSignal(d._watcher.directoryChanged, timeout=3000):
            subprocess.run(
                ["git", "-C", str(repo), "worktree", "add", str(wt_path), "feat"],
                check=True, capture_output=True,
            )
        qtbot.wait(300)  # let the 200 ms debounce fire
        assert calls, "expected on_reload to fire after external worktree add"
    finally:
        d.stop()
