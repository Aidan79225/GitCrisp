import contextlib
import subprocess
from pathlib import Path

import pytest

from git_gui.infrastructure.submodule_cli import (
    SubmoduleCli,
    SubmoduleCommandError,
)


def _run(cwd: str, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=cwd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


@pytest.fixture
def parent_and_child(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "protocol.file.allow")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "always")

    child = tmp_path / "child"
    child.mkdir()
    _run(str(child), "init", "-q", "-b", "main")
    _run(str(child), "config", "user.email", "t@t")
    _run(str(child), "config", "user.name", "t")
    (child / "f.txt").write_text("hi")
    _run(str(child), "add", ".")
    _run(str(child), "commit", "-q", "-m", "init")

    parent = tmp_path / "parent"
    parent.mkdir()
    _run(str(parent), "init", "-q", "-b", "main")
    _run(str(parent), "config", "user.email", "t@t")
    _run(str(parent), "config", "user.name", "t")
    (parent / "r.txt").write_text("root")
    _run(str(parent), "add", ".")
    _run(str(parent), "commit", "-q", "-m", "root")
    return parent, child


def test_add_submodule_creates_gitmodules(parent_and_child):
    parent, child = parent_and_child
    cli = SubmoduleCli(str(parent))
    cli.add(path="libs/foo", url=str(child))
    assert (parent / ".gitmodules").exists()
    assert (parent / "libs" / "foo" / "f.txt").exists()


def test_add_submodule_leaves_dot_git_gitlink(parent_and_child):
    """After add, the submodule workdir must have a .git file or dir so that
    git and pygit2 can find the submodule's gitdir without walking up."""
    parent, child = parent_and_child
    cli = SubmoduleCli(str(parent))
    cli.add(path="libs/foo", url=str(child))
    dot_git = parent / "libs" / "foo" / ".git"
    assert dot_git.exists(), (
        "submodule workdir is missing .git — submodule is not initialized. "
        "git/pygit2 will walk up to the parent repo when operating on it."
    )


def test_set_url_updates_gitmodules(parent_and_child):
    parent, child = parent_and_child
    cli = SubmoduleCli(str(parent))
    cli.add(path="libs/foo", url=str(child))
    new_url = str(child) + "#renamed"
    cli.set_url("libs/foo", new_url)
    text = (parent / ".gitmodules").read_text()
    assert "renamed" in text


def test_remove_clears_submodule(parent_and_child):
    parent, child = parent_and_child
    cli = SubmoduleCli(str(parent))
    cli.add(path="libs/foo", url=str(child))
    cli.remove("libs/foo")
    assert not (parent / "libs" / "foo").exists()
    gm = parent / ".gitmodules"
    if gm.exists():
        assert "libs/foo" not in gm.read_text()


def test_missing_git_raises_friendly_error(parent_and_child):
    parent, _ = parent_and_child
    cli = SubmoduleCli(str(parent), git_executable="definitely-not-git-xyz")
    with pytest.raises(SubmoduleCommandError) as ei:
        cli.add(path="libs/foo", url="anything")
    assert "not found" in str(ei.value).lower()


def _git_output(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_set_url_edits_the_section_of_a_submodule_named_unlike_its_path(parent_and_child):
    parent, child = parent_and_child
    _run(str(parent), "submodule", "add", "--name", "gtest", "--", str(child), "third_party/gtest")
    new_url = str(child) + "#renamed"

    SubmoduleCli(str(parent)).set_url("third_party/gtest", new_url)

    assert _git_output(parent, "config", "-f", ".gitmodules", "submodule.gtest.url") == new_url
    assert "third_party/gtest" not in _git_output(
        parent, "config", "-f", ".gitmodules", "--name-only", "--list"
    )


def test_remove_leaves_files_that_only_match_the_path_as_a_glob(parent_and_child):
    parent, child = parent_and_child
    cli = SubmoduleCli(str(parent))
    cli.add(path="lib[1]", url=str(child))
    (parent / "lib1").write_text("committed")
    _run(str(parent), "add", "lib1")
    _run(str(parent), "commit", "-q", "-m", "add lib1 and lib[1]")
    (parent / "lib1").write_text("uncommitted work")

    cli.remove("lib[1]")

    assert (parent / "lib1").read_text() == "uncommitted work"


def test_a_removed_submodule_can_be_added_again_at_the_same_path(parent_and_child):
    parent, child = parent_and_child
    cli = SubmoduleCli(str(parent))
    cli.add(path="libs/foo", url=str(child))
    cli.remove("libs/foo")

    cli.add(path="libs/foo", url=str(child))

    assert (parent / "libs" / "foo" / "f.txt").exists()


def test_remove_deletes_the_git_dir_of_a_submodule_named_unlike_its_path(parent_and_child):
    parent, child = parent_and_child
    _run(str(parent), "submodule", "add", "--name", "gtest", "--", str(child), "third_party/gtest")
    assert (parent / ".git" / "modules" / "gtest").is_dir()

    SubmoduleCli(str(parent)).remove("third_party/gtest")

    assert not (parent / ".git" / "modules" / "gtest").exists()


def test_a_submodule_removed_in_a_linked_worktree_can_be_added_again(parent_and_child, tmp_path):
    parent, child = parent_and_child
    worktree = tmp_path / "wt"
    _run(str(parent), "worktree", "add", "-q", str(worktree))
    cli = SubmoduleCli(str(worktree))
    cli.add(path="libs/foo", url=str(child))
    cli.remove("libs/foo")

    cli.add(path="libs/foo", url=str(child))

    assert (worktree / "libs" / "foo" / "f.txt").exists()


def test_remove_never_deletes_outside_the_modules_dir(parent_and_child):
    parent, child = parent_and_child
    cli = SubmoduleCli(str(parent))
    cli.add(path="libs/foo", url=str(child))
    _run(
        str(parent),
        "config",
        "-f",
        ".gitmodules",
        "--rename-section",
        "submodule.libs/foo",
        "submodule.../..",
    )
    _run(str(parent), "add", ".gitmodules")

    with contextlib.suppress(SubmoduleCommandError):
        cli.remove("libs/foo")

    assert (parent / "r.txt").exists()
