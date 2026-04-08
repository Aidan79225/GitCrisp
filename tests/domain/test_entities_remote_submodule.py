from git_gui.domain.entities import Remote, Submodule


def test_remote_dataclass_fields():
    r = Remote(name="origin", fetch_url="git@x:a.git", push_url="git@x:a.git")
    assert r.name == "origin"
    assert r.fetch_url == "git@x:a.git"
    assert r.push_url == "git@x:a.git"


def test_submodule_dataclass_fields():
    s = Submodule(path="libs/foo", url="git@x:foo.git", head_sha="abc123")
    assert s.path == "libs/foo"
    assert s.url == "git@x:foo.git"
    assert s.head_sha == "abc123"


def test_submodule_head_sha_optional():
    s = Submodule(path="libs/foo", url="git@x:foo.git", head_sha=None)
    assert s.head_sha is None
