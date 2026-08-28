import subprocess
from pathlib import Path

import pytest

from git_gui.infrastructure.pygit2 import Pygit2Repository


def _run(cwd, *args):
    subprocess.run(
        ["git", *args], cwd=cwd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


@pytest.fixture
def repo(tmp_path: Path):
    p = tmp_path / "r"
    p.mkdir()
    _run(str(p), "init", "-q", "-b", "master")
    _run(str(p), "config", "user.email", "t@t")
    _run(str(p), "config", "user.name", "t")
    (p / "f.txt").write_text("hi")
    _run(str(p), "add", ".")
    _run(str(p), "commit", "-q", "-m", "init")
    _run(str(p), "remote", "add", "origin", str(p))
    _run(str(p), "fetch", "-q", "origin")
    return Pygit2Repository(str(p)), p


def test_list_local_branches_no_upstream(repo):
    r, _ = repo
    infos = r.list_local_branches_with_upstream()
    assert len(infos) == 1
    info = infos[0]
    assert info.name == "master"
    assert info.upstream is None
    assert len(info.last_commit_sha) >= 7
    assert info.last_commit_message == "init"


def test_set_and_list_upstream(repo):
    r, _ = repo
    r.set_branch_upstream("master", "origin/master")
    infos = r.list_local_branches_with_upstream()
    assert infos[0].upstream == "origin/master"


def test_unset_upstream(repo):
    r, _ = repo
    r.set_branch_upstream("master", "origin/master")
    r.unset_branch_upstream("master")
    assert r.list_local_branches_with_upstream()[0].upstream is None


def test_rename_branch(repo):
    r, p = repo
    _run(str(p), "branch", "feature")
    r.rename_branch("feature", "feature2")
    names = [i.name for i in r.list_local_branches_with_upstream()]
    assert "feature2" in names
    assert "feature" not in names


def test_reset_branch_to_ref_resolves_an_annotated_tag_to_its_commit(repo):
    """An annotated tag's own oid is not the commit's — peel before resetting.

    libgit2 happens to peel it for us, so this pins the behaviour rather than
    reporting a break: the code now names the object it wants instead of
    relying on reset to work that out.
    """
    import pygit2

    r, p = repo
    raw = pygit2.Repository(str(p))
    first = str(raw.head.target)
    (p / "later.txt").write_text("later")
    _run(str(p), "add", ".")
    _run(str(p), "commit", "-q", "-m", "later")
    _run(str(p), "tag", "-a", "v1.0", first, "-m", "annotated")

    raw = pygit2.Repository(str(p))
    tag_oid = str(raw.revparse_single("v1.0").id)
    assert tag_oid != first, "an annotated tag must be its own object for this to test anything"

    r.reset_branch_to_ref("master", "v1.0")

    assert str(pygit2.Repository(str(p)).head.target) == first


def test_reset_branch_to_ref(repo):
    r, p = repo
    (p / "g.txt").write_text("g")
    _run(str(p), "add", ".")
    _run(str(p), "commit", "-q", "-m", "second")
    second_sha = r.list_local_branches_with_upstream()[0].last_commit_sha
    _run(str(p), "branch", "side")
    (p / "h.txt").write_text("h")
    _run(str(p), "add", ".")
    _run(str(p), "commit", "-q", "-m", "third")
    _run(str(p), "checkout", "-q", "side")
    r.reset_branch_to_ref("side", "master")
    side_info = next(i for i in r.list_local_branches_with_upstream() if i.name == "side")
    assert side_info.last_commit_sha != second_sha
