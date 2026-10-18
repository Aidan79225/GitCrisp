"""git's messages reach the caller even when they are not ASCII.

git writes paths, ref names and commit subjects as UTF-8 whatever the OS
locale. On Windows the locale code page (cp950, cp1252, ...) cannot decode
every UTF-8 byte; "Ł" is one such character for both, so these tests fail
there if the output is decoded with it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pygit2
import pytest

from git_gui.infrastructure.file_history_cli import FileHistoryCli, FileHistoryError
from git_gui.infrastructure.pygit2 import Pygit2Repository

NAME = "Łódź"


def _git(cwd: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args], check=check, capture_output=True, encoding="utf-8"
    )
    return result.stdout.strip()


def _commit(repo: Path, content: str, subject: str) -> str:
    (repo / "f.txt").write_text(content, encoding="utf-8")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-q", "-m", subject)
    return _git(repo, "rev-parse", "HEAD")


def test_file_history_on_an_unborn_branch_keeps_git_s_message(tmp_path):
    pygit2.init_repository(str(tmp_path), initial_head=NAME)

    with pytest.raises(FileHistoryError, match=NAME):
        FileHistoryCli(str(tmp_path)).commit_oids("f.txt", limit=10)


def test_a_continued_rebase_that_conflicts_again_names_the_commit(repo_path):
    _commit(repo_path, "base", "base")
    _git(repo_path, "checkout", "-q", "-b", "topic")
    _commit(repo_path, "topic one", f"{NAME} one")
    _commit(repo_path, "topic two", f"{NAME} two")
    _git(repo_path, "checkout", "-q", "master")
    _commit(repo_path, "master", "master")
    _git(repo_path, "checkout", "-q", "topic")
    _git(repo_path, "rebase", "master", check=False)  # Stops at "one".
    (repo_path / "f.txt").write_text("resolved", encoding="utf-8")
    _git(repo_path, "add", "f.txt")

    with pytest.raises(RuntimeError, match=f"{NAME} two"):
        Pygit2Repository(str(repo_path)).rebase_continue()


def test_an_interactive_rebase_refused_by_a_hook_keeps_the_hook_s_message(repo_path):
    hooks = repo_path / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    hook = hooks / "pre-rebase"
    hook.write_text(f"#!/bin/sh\necho '{NAME} is frozen' >&2\nexit 1\n", "utf-8", newline="\n")
    hook.chmod(0o755)
    _git(repo_path, "config", "core.hooksPath", hooks.as_posix())
    base = _git(repo_path, "rev-parse", "HEAD")
    tip = _commit(repo_path, "tip", "tip")

    with pytest.raises(RuntimeError, match=f"{NAME} is frozen"):
        Pygit2Repository(str(repo_path)).interactive_rebase(base, [("pick", tip)])


def test_saving_the_identity_into_a_locked_config_names_the_file(tmp_path):
    workdir = tmp_path / NAME
    pygit2.init_repository(str(workdir))
    (workdir / ".git" / "config.lock").touch()

    with pytest.raises(RuntimeError, match=NAME):
        Pygit2Repository(str(workdir)).set_identity("T", "t@example.com", global_=False)


def test_a_submodule_at_a_non_ascii_path_shows_its_commit(repo_path):
    _git(repo_path, "config", "core.quotepath", "false")
    head = _git(repo_path, "rev-parse", "HEAD")
    (repo_path / ".gitmodules").write_text(
        f'[submodule "{NAME}"]\n\tpath = {NAME}\n\turl = ./elsewhere\n', encoding="utf-8"
    )
    _git(repo_path, "update-index", "--add", "--cacheinfo", f"160000,{head},{NAME}")

    submodules = Pygit2Repository(str(repo_path)).list_submodules()

    assert [(s.path, s.head_sha) for s in submodules] == [(NAME, head)]
