"""The git CLI wrappers run against the repository they were given.

Left to discover the repository from the working directory, git walks up
from a submodule whose `.git` link is missing and lands on the parent — a
layout the app opens on purpose (see `_resolve_gitdir`). Handing the wrappers
the gitdir pins every command to the submodule itself.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from git_gui.infrastructure.commit_ops_cli import CommitOpsCli
from git_gui.infrastructure.file_history_cli import FileHistoryCli

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs the git CLI")


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit(workdir: Path, name: str, message: str) -> str:
    (workdir / name).write_text(message, encoding="utf-8")
    _git(workdir, "add", name)
    _git(workdir, "commit", "-q", "-m", message)
    return _git(workdir, "rev-parse", "HEAD")


@pytest.fixture
def unlinked_submodule(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    """`parent/sub`, a submodule whose gitdir lives in the parent but whose `.git` link is gone.

    Returns (workdir, gitdir, oids): `base` is on the submodule's checked-out
    branch, `side` only on a branch beside it.
    """
    parent = tmp_path / "parent"
    _git(tmp_path, "init", "-q", "-b", "master", str(parent))
    (parent / ".gitmodules").write_text(
        '[submodule "sub"]\n\tpath = sub\n\turl = ./sub\n', encoding="utf-8"
    )
    _commit(parent, "parent.txt", "parent only")

    # Laid out as `git submodule add` leaves it, minus the network clone.
    workdir = parent / "sub"
    gitdir = parent / ".git" / "modules" / "sub"
    gitdir.parent.mkdir()
    _git(tmp_path, "init", "-q", "-b", "master", f"--separate-git-dir={gitdir}", str(workdir))
    _git(workdir, "config", "core.worktree", "../../../sub")
    _git(workdir, "config", "user.name", "T")
    _git(workdir, "config", "user.email", "t@example.com")
    oids = {"base": _commit(workdir, "f.txt", "base")}
    _git(workdir, "checkout", "-q", "-b", "side")
    oids["side"] = _commit(workdir, "side.txt", "side")
    _git(workdir, "checkout", "-q", "master")

    (workdir / ".git").unlink()
    return workdir, gitdir, oids


def test_file_history_reads_the_submodule_not_its_parent(unlinked_submodule):
    workdir, gitdir, oids = unlinked_submodule
    cli = FileHistoryCli(str(workdir), git_dir=str(gitdir))

    assert cli.commit_oids("f.txt", limit=10) == [oids["base"]]


def test_cherry_pick_applies_a_submodule_commit_to_the_submodule(unlinked_submodule):
    workdir, gitdir, oids = unlinked_submodule
    cli = CommitOpsCli(str(workdir), git_dir=str(gitdir))

    cli.cherry_pick(oids["side"], is_merge=False)

    assert (workdir / "side.txt").read_text(encoding="utf-8") == "side"
