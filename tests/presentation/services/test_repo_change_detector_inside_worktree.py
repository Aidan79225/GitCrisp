"""Auto-refresh while the open repo *is* a linked worktree.

`.git` is a directory only in an ordinary clone. In a linked worktree — and in
a submodule — it is a one-line file pointing elsewhere, so the old `is_dir()`
test found nothing and the detector returned having watched not one path: no
external commit, fetch or branch switch ever reached the window.

A worktree also splits its state in two. `HEAD` and `index` live in the
per-worktree directory the pointer names; `refs/`, `packed-refs` and the
objects stay in the common directory beside them. Watching either one alone
is half a fix, so the tests below check both ends.

Every repo here is built by the git CLI rather than by hand: the pointer
formats are git's to define, and a fixture that writes what we assume git
writes would test the assumption rather than the code.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pytest

from git_gui.presentation.services.repo_change_detector import (
    RepoChangeDetector,
    resolve_git_dirs,
)

DETECTOR_LOGGER = "git_gui.presentation.services.repo_change_detector"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _init(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", ".")
    _git(path, "config", "user.name", "T")
    _git(path, "config", "user.email", "t@e.com")
    (path / "a.txt").write_text("x\n")
    _git(path, "add", "a.txt")
    _git(path, "commit", "-qm", "init")
    # A remote, so refs/remotes exists — git does not create it until the first
    # fetch, and a repo that has never fetched is not the case worth testing.
    _git(path, "remote", "add", "origin", ".")
    _git(path, "fetch", "-q", "origin")
    return path


@pytest.fixture
def clone(tmp_path) -> Path:
    """An ordinary clone — `.git` is a directory."""
    return _init(tmp_path / "main")


@pytest.fixture
def worktree(clone, tmp_path) -> Path:
    """A linked worktree of `clone` — `.git` is a file."""
    path = tmp_path / "linked"
    _git(clone, "worktree", "add", "-q", str(path), "-b", "feature")
    return path


@pytest.fixture
def submodule(tmp_path) -> Path:
    """A submodule checkout — `.git` is a file too, pointing at a *relative*
    directory that is complete on its own."""
    lib = _init(tmp_path / "lib")
    super_ = _init(tmp_path / "super")
    _git(
        super_,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(lib),
        "lib",
    )
    _git(super_, "commit", "-qm", "add submodule")
    return super_ / "lib"


def _watched(qtbot, path: Path) -> set[str]:
    d = RepoChangeDetector(str(path), on_reload=lambda: None)
    try:
        return set(d._watcher.files()) | set(d._watcher.directories())
    finally:
        d.stop()


# ── Resolving the two directories ────────────────────────────────────────────


def test_an_ordinary_clone_has_one_directory(clone):
    git_dir, common_dir = resolve_git_dirs(clone)

    assert git_dir == common_dir == clone / ".git"


def test_a_worktree_has_two_different_directories(clone, worktree):
    git_dir, common_dir = resolve_git_dirs(worktree)

    assert git_dir == clone / ".git" / "worktrees" / "linked"
    assert common_dir == clone / ".git"


def test_a_submodule_resolves_its_relative_pointer(submodule):
    """git writes a submodule's pointer relative to the checkout, unlike a
    worktree's, so a resolver that only handled absolute paths would watch a
    directory that does not exist."""
    git_dir, common_dir = resolve_git_dirs(submodule)

    assert git_dir == submodule.parent / ".git" / "modules" / "lib"
    assert git_dir.is_dir()
    # No commondir file: a submodule keeps its own refs and objects.
    assert common_dir == git_dir


def test_a_directory_with_no_repo_resolves_to_nothing(tmp_path):
    assert resolve_git_dirs(tmp_path) is None


def test_a_pointer_to_a_missing_directory_resolves_to_nothing(tmp_path):
    """A worktree whose repo was deleted out from under it. Watching whatever
    the stale path happens to be is worse than watching nothing."""
    orphan = tmp_path / "orphan"
    orphan.mkdir()
    (orphan / ".git").write_text("gitdir: /nowhere/at/all\n")

    assert resolve_git_dirs(orphan) is None


# ── What ends up watched ─────────────────────────────────────────────────────


def test_a_worktree_watches_anything_at_all(qtbot, worktree):
    """The whole bug in one line: this was empty."""
    assert _watched(qtbot, worktree) != set()


def test_a_worktree_watches_its_own_head(qtbot, clone, worktree):
    """Per-worktree state. Without it, this worktree's own branch switches and
    commits go unnoticed."""
    watched = _watched(qtbot, worktree)

    assert str(clone / ".git" / "worktrees" / "linked" / "HEAD") in watched
    assert str(clone / ".git" / "worktrees" / "linked" / "index") in watched


def test_a_worktree_watches_the_refs_it_shares(qtbot, clone, worktree):
    """Shared state. Without it, a fetch or a branch created anywhere else in
    the repo goes unnoticed."""
    watched = _watched(qtbot, worktree)

    assert str(clone / ".git" / "refs" / "heads") in watched
    assert str(clone / ".git" / "refs" / "remotes") in watched


def test_a_submodule_watches_its_own_directory(qtbot, submodule):
    watched = _watched(qtbot, submodule)
    git_dir = submodule.parent / ".git" / "modules" / "lib"

    assert str(git_dir / "HEAD") in watched
    assert str(git_dir / "refs" / "heads") in watched


def test_an_ordinary_clone_still_watches_what_it_did(qtbot, clone):
    """The common case must not pay for the fix."""
    watched = _watched(qtbot, clone)
    git_dir = clone / ".git"

    for name in ("HEAD", "index"):
        assert str(git_dir / name) in watched
    for name in ("refs/heads", "refs/remotes", "refs/tags", "logs"):
        assert str(git_dir / name) in watched
    assert str(git_dir) in watched


def test_no_path_is_looked_up_twice(qtbot, clone, worktree, caplog):
    """Both roots are searched for every name, and in a clone the two roots are
    the same directory. Qt refuses a path it already watches, so a second pass
    costs no watches — it logs a failure for every path being watched
    perfectly well, which is how a real one gets lost."""
    for path in (clone, worktree):
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger=DETECTOR_LOGGER):
            d = RepoChangeDetector(str(path), on_reload=lambda: None)
            d.stop()
        assert caplog.records == [], path


# ── The behaviour all of that is for ─────────────────────────────────────────


def test_a_commit_made_outside_the_app_reaches_the_callback(qtbot, worktree):
    """End to end, in the shape the bug was reported in: work in a worktree,
    commit from a terminal, and the window should notice."""
    calls: list[None] = []
    d = RepoChangeDetector(str(worktree), on_reload=lambda: calls.append(None))
    try:
        (worktree / "a.txt").write_text("changed\n")
        _git(worktree, "add", "a.txt")
        _git(worktree, "commit", "-qm", "outside the app")

        qtbot.waitUntil(lambda: bool(calls), timeout=5000)
    finally:
        d.stop()


def test_a_branch_created_elsewhere_reaches_the_callback(qtbot, clone, worktree):
    """The shared half: nothing happened inside this worktree at all."""
    calls: list[None] = []
    d = RepoChangeDetector(str(worktree), on_reload=lambda: calls.append(None))
    try:
        _git(clone, "branch", "made-elsewhere")

        qtbot.waitUntil(lambda: bool(calls), timeout=5000)
    finally:
        d.stop()
