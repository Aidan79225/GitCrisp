"""RepoStateOps mixin — merge state files and identity writes."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pygit2
import pytest

from git_gui.infrastructure.pygit2 import Pygit2Repository


def test_get_merge_msg_reads_utf8_whatever_the_locale(repo_path, repo_impl):
    # git writes MERGE_MSG as UTF-8. These bytes are undecodable in cp1252 and
    # cp950, the ANSI code pages a Windows open() would otherwise fall back to.
    message = "Merge branch '功能'\n\n#Conflicts:\n#\tŁódź.txt\n"
    merge_msg = Path(pygit2.Repository(str(repo_path)).path) / "MERGE_MSG"
    merge_msg.write_bytes(message.encode("utf-8"))

    assert repo_impl.get_merge_msg() == message


@pytest.mark.skipif(sys.platform != "win32", reason="only Windows opens console windows")
def test_set_identity_runs_git_without_a_console_window(repo_impl, monkeypatch):
    creationflags: list[int] = []
    real_run = subprocess.run

    def recording_run(*args, **kwargs):
        creationflags.append(kwargs.get("creationflags", 0))
        return real_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", recording_run)

    repo_impl.set_identity("Ada", "ada@example.com", global_=False)

    assert creationflags
    assert all(flags & subprocess.CREATE_NO_WINDOW for flags in creationflags)


# ── a remote libgit2 rejects ────────────────────────────────────────────────


def _git(cwd, *args) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def clone_with_a_remote_libgit2_rejects(tmp_path):
    """A clone of a local bare origin whose config also names a remote git
    runs with but libgit2 will not look up: a space is not valid in its name."""
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "master", str(remote))
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(remote), str(clone))
    _git(clone, "config", "user.email", "t@t")
    _git(clone, "config", "user.name", "t")
    (clone / "f.txt").write_text("".join(f"line {i}\n" for i in range(1, 21)))
    _git(clone, "add", ".")
    _git(clone, "commit", "-q", "-m", "init")
    _git(clone, "push", "-q", "origin", "master")
    with open(clone / ".git" / "config", "a", encoding="utf-8") as config:
        config.write('[remote "bad name"]\n\turl = https://example.invalid/x.git\n')
    return clone


def test_git_commands_still_run_beside_a_remote_libgit2_rejects(
    clone_with_a_remote_libgit2_rejects,
):
    clone = clone_with_a_remote_libgit2_rejects
    impl = Pygit2Repository(str(clone))
    (clone / "f.txt").write_text("".join(f"line {i}\n" for i in range(1, 20)) + "changed\n")

    assert impl.is_dirty() is True
    impl.stage_hunk("f.txt", impl.get_file_diff("WORKING_TREE", "f.txt")[0].header)
    assert _git(clone, "diff", "--cached", "--name-only").strip() == "f.txt"
    _git(clone, "commit", "-q", "-m", "change")
    impl.pull("origin", "master")
