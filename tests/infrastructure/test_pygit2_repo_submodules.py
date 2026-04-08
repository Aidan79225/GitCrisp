import subprocess
from pathlib import Path
import pytest

from git_gui.infrastructure.pygit2_repo import Pygit2Repository


def _run(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.fixture
def parent_repo(tmp_path: Path, monkeypatch):
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
    return Pygit2Repository(str(parent)), str(child), parent


def test_list_submodules_empty(parent_repo):
    repo, _, _ = parent_repo
    assert repo.list_submodules() == []


def test_add_then_list_submodule(parent_repo):
    repo, child_url, parent_path = parent_repo
    repo.add_submodule("libs/foo", child_url)
    subs = repo.list_submodules()
    assert len(subs) == 1
    assert subs[0].path == "libs/foo"
    assert subs[0].head_sha is not None


def test_set_submodule_url(parent_repo):
    repo, child_url, parent_path = parent_repo
    repo.add_submodule("libs/foo", child_url)
    new_url = child_url + "#renamed"
    repo.set_submodule_url("libs/foo", new_url)
    text = (parent_path / ".gitmodules").read_text()
    assert "renamed" in text


def test_remove_submodule(parent_repo):
    repo, child_url, parent_path = parent_repo
    repo.add_submodule("libs/foo", child_url)
    repo.remove_submodule("libs/foo")
    assert repo.list_submodules() == []
