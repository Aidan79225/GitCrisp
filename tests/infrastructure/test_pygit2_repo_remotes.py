import subprocess
from pathlib import Path
import pytest

from git_gui.infrastructure.pygit2_repo import Pygit2Repository


def _run(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.fixture
def repo(tmp_path: Path):
    p = tmp_path / "r"
    p.mkdir()
    _run(str(p), "init", "-q", "-b", "main")
    _run(str(p), "config", "user.email", "t@t")
    _run(str(p), "config", "user.name", "t")
    (p / "f.txt").write_text("hi")
    _run(str(p), "add", ".")
    _run(str(p), "commit", "-q", "-m", "init")
    return Pygit2Repository(str(p))


def test_list_remotes_empty(repo):
    assert repo.list_remotes() == []


def test_add_then_list_remote(repo):
    repo.add_remote("origin", "git@example.com:a.git")
    remotes = repo.list_remotes()
    assert len(remotes) == 1
    assert remotes[0].name == "origin"
    assert remotes[0].fetch_url == "git@example.com:a.git"
    assert remotes[0].push_url == "git@example.com:a.git"


def test_rename_remote(repo):
    repo.add_remote("origin", "git@example.com:a.git")
    repo.rename_remote("origin", "upstream")
    names = [r.name for r in repo.list_remotes()]
    assert names == ["upstream"]


def test_set_remote_url(repo):
    repo.add_remote("origin", "git@example.com:a.git")
    repo.set_remote_url("origin", "git@example.com:b.git")
    assert repo.list_remotes()[0].fetch_url == "git@example.com:b.git"


def test_remove_remote(repo):
    repo.add_remote("origin", "git@example.com:a.git")
    repo.remove_remote("origin")
    assert repo.list_remotes() == []
