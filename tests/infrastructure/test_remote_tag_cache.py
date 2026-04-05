import json
import pytest
from pathlib import Path
from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache


@pytest.fixture
def cache(tmp_path) -> JsonRemoteTagCache:
    return JsonRemoteTagCache(tmp_path / "remote_tags")


def test_load_returns_empty_when_no_file(cache):
    result = cache.load("/some/repo/path")
    assert result == {}


def test_save_and_load_roundtrip(cache):
    data = {"origin": ["v1.0.0", "v2.0.0"]}
    cache.save("/some/repo/path", data)
    result = cache.load("/some/repo/path")
    assert result == data


def test_different_repos_have_separate_caches(cache):
    cache.save("/repo/a", {"origin": ["v1.0"]})
    cache.save("/repo/b", {"origin": ["v2.0"]})
    assert cache.load("/repo/a") == {"origin": ["v1.0"]}
    assert cache.load("/repo/b") == {"origin": ["v2.0"]}


def test_save_creates_directory(tmp_path):
    cache_dir = tmp_path / "nested" / "remote_tags"
    cache = JsonRemoteTagCache(cache_dir)
    cache.save("/repo", {"origin": ["v1.0"]})
    assert cache.load("/repo") == {"origin": ["v1.0"]}
