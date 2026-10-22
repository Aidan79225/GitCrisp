import os
import subprocess
import sys
from pathlib import Path

import pygit2
import pytest

from git_gui.infrastructure.pygit2 import Pygit2Repository


def _seed(repo_path: Path) -> Pygit2Repository:
    impl = Pygit2Repository(str(repo_path))
    (repo_path / "a.txt").write_text("original\n")
    impl.stage(["a.txt"])
    impl.commit("seed")
    return impl


def test_discard_modified_file_reverts_to_head(repo_path):
    impl = _seed(repo_path)
    (repo_path / "a.txt").write_text("modified\n")
    impl.discard_file("a.txt")
    assert (repo_path / "a.txt").read_text() == "original\n"


def test_discard_deleted_file_restores(repo_path):
    impl = _seed(repo_path)
    (repo_path / "a.txt").unlink()
    impl.discard_file("a.txt")
    assert (repo_path / "a.txt").read_text() == "original\n"


def test_discard_untracked_file_unlinks(repo_path):
    impl = _seed(repo_path)
    (repo_path / "new.txt").write_text("hello\n")
    impl.discard_file("new.txt")
    assert not (repo_path / "new.txt").exists()


def test_discard_of_an_untracked_file_leaves_an_index_another_program_holds_alone(repo_path):
    # An editor's own `git status` holds index.lock now and then. An untracked
    # file is not in the index, so its discard has nothing to write there.
    impl = _seed(repo_path)
    (repo_path / "new.txt").write_text("hello\n")
    index_lock = repo_path / ".git" / "index.lock"
    index_lock.touch()

    impl.discard_file("new.txt")

    assert not (repo_path / "new.txt").exists()
    assert index_lock.exists()


def test_discard_staged_add_unstages_and_unlinks(repo_path):
    impl = _seed(repo_path)
    (repo_path / "added.txt").write_text("staged add\n")
    impl.stage(["added.txt"])
    impl.discard_file("added.txt")
    assert not (repo_path / "added.txt").exists()
    assert "added.txt" not in [e.path for e in impl._repo.index]


def test_discard_modified_with_staged_changes_fully_resets(repo_path):
    impl = _seed(repo_path)
    (repo_path / "a.txt").write_text("staged change\n")
    impl.stage(["a.txt"])
    (repo_path / "a.txt").write_text("further unstaged\n")
    impl.discard_file("a.txt")
    assert (repo_path / "a.txt").read_text() == "original\n"
    head_commit = impl._repo.head.peel(pygit2.Commit)
    head_blob_id = head_commit.tree["a.txt"].id
    assert impl._repo.index["a.txt"].id == head_blob_id


def test_discard_hunk_reverts_only_that_hunk(repo_path):
    impl = Pygit2Repository(str(repo_path))
    lines = [f"line {i}\n" for i in range(1, 21)]
    (repo_path / "multi.txt").write_text("".join(lines))
    impl.stage(["multi.txt"])
    impl.commit("seed multi")

    lines[1] = "CHANGED line 2\n"
    lines[17] = "CHANGED line 18\n"
    (repo_path / "multi.txt").write_text("".join(lines))

    from git_gui.domain.entities import WORKING_TREE_OID

    hunks = impl.get_file_diff(WORKING_TREE_OID, "multi.txt")
    assert len(hunks) == 2

    impl.discard_hunk("multi.txt", hunks[0].header)

    text = (repo_path / "multi.txt").read_text()
    assert "line 2\n" in text
    assert "CHANGED line 2" not in text
    assert "CHANGED line 18\n" in text


def _symlink_or_skip(target: str, link: Path) -> None:
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("this platform cannot create symlinks")


def test_discard_restores_the_line_endings_checkout_would_write(repo_path):
    impl = Pygit2Repository(str(repo_path))
    (repo_path / ".gitattributes").write_bytes(b"*.bat text eol=crlf\n")
    (repo_path / "run.bat").write_bytes(b"@echo off\r\necho hi\r\n")
    impl.stage([".gitattributes", "run.bat"])
    impl.commit("seed bat")
    (repo_path / "run.bat").write_bytes(b"@echo off\r\necho bye\r\n")

    impl.discard_file("run.bat")

    assert (repo_path / "run.bat").read_bytes() == b"@echo off\r\necho hi\r\n"


@pytest.mark.skipif(sys.platform == "win32", reason="no executable bit on Windows")
def test_discard_restores_a_deleted_script_as_executable(repo_path):
    impl = Pygit2Repository(str(repo_path))
    script = repo_path / "run.sh"
    script.write_text("#!/bin/sh\necho hi\n")
    script.chmod(0o755)
    impl.stage(["run.sh"])
    impl.commit("seed script")
    script.unlink()

    impl.discard_file("run.sh")

    assert script.stat().st_mode & 0o111


def test_discard_points_a_retargeted_symlink_back_without_touching_its_target(repo_path):
    impl = Pygit2Repository(str(repo_path))
    (repo_path / "defaults.yml").write_text("defaults\n")
    (repo_path / "local.yml").write_text("local\n")
    link = repo_path / "cfg"
    _symlink_or_skip("defaults.yml", link)
    impl.stage(["defaults.yml", "local.yml", "cfg"])
    impl.commit("seed link")
    link.unlink()
    os.symlink("local.yml", link)

    impl.discard_file("cfg")

    assert os.readlink(link) == "defaults.yml"
    assert (repo_path / "local.yml").read_text() == "local\n"


def test_discard_of_a_glob_like_name_leaves_the_files_it_would_match_alone(repo_path):
    impl = Pygit2Repository(str(repo_path))
    (repo_path / "f[1].txt").write_text("bracket\n")
    (repo_path / "f1.txt").write_text("plain\n")
    impl.stage(["f[1].txt", "f1.txt"])
    impl.commit("seed glob-like names")
    (repo_path / "f[1].txt").write_text("bracket edited\n")
    (repo_path / "f1.txt").write_text("plain edited\n")

    impl.discard_file("f[1].txt")

    assert (repo_path / "f[1].txt").read_text() == "bracket\n"
    assert (repo_path / "f1.txt").read_text() == "plain edited\n"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_discard_on_a_moved_submodule_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "protocol.file.allow")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "always")
    child, parent = tmp_path / "child", tmp_path / "parent"
    for repo in (child, parent):
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        _git(repo, "commit", "-q", "--allow-empty", "-m", "root")
    _git(parent, "submodule", "add", "-q", str(child), "sub")
    _git(parent, "commit", "-q", "-m", "add sub")
    head_gitlink = pygit2.Repository(str(parent)).head.peel(pygit2.Commit).tree["sub"].id
    _git(
        parent / "sub",
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "moved",
    )
    _git(parent, "add", "sub")
    impl = Pygit2Repository(str(parent))

    impl.discard_file("sub")

    assert impl._repo.index["sub"].id == head_gitlink
