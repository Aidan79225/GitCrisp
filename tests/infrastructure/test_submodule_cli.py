import subprocess
from pathlib import Path
import pytest

from git_gui.infrastructure.submodule_cli import (
    SubmoduleCli, SubmoduleCommandError,
)


def _run(cwd: str, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.fixture
def parent_and_child(tmp_path: Path):
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
    _run(str(parent), "config", "protocol.file.allow", "always")
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
