import json
from pathlib import Path

import pytest

from git_gui.infrastructure.repo_store import JsonRepoStore


@pytest.fixture
def store_path(tmp_path) -> Path:
    return tmp_path / ".gitcrisp" / "repos.json"


@pytest.fixture
def store(store_path) -> JsonRepoStore:
    return JsonRepoStore(store_path)


class TestJsonRepoStoreLoad:
    def test_load_missing_file_returns_empty_state(self, store):
        store.load()
        assert store.get_open_repos() == []
        assert store.get_recent_repos() == []
        assert store.get_active() is None

    def test_load_existing_file(self, store, store_path):
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(
            json.dumps(
                {
                    "open": ["/repo/a", "/repo/b"],
                    "recent": ["/repo/c"],
                    "active": "/repo/a",
                }
            )
        )
        store.load()
        assert store.get_open_repos() == ["/repo/a", "/repo/b"]
        assert store.get_recent_repos() == ["/repo/c"]
        assert store.get_active() == "/repo/a"


class TestJsonRepoStoreSave:
    def test_save_creates_directory_and_file(self, store, store_path):
        store.load()
        store.add_open("/repo/a")
        store.save()
        assert store_path.exists()
        data = json.loads(store_path.read_text())
        assert data["open"] == ["/repo/a"]
        assert data["active"] == "/repo/a"


class TestJsonRepoStoreAddOpen:
    def test_add_open_sets_active(self, store):
        store.load()
        store.add_open("/repo/a")
        assert store.get_open_repos() == ["/repo/a"]
        assert store.get_active() == "/repo/a"

    def test_add_open_removes_from_recent(self, store, store_path):
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(
            json.dumps(
                {
                    "open": [],
                    "recent": ["/repo/a", "/repo/b"],
                    "active": None,
                }
            )
        )
        store.load()
        store.add_open("/repo/a")
        assert "/repo/a" not in store.get_recent_repos()
        assert store.get_open_repos() == ["/repo/a"]

    def test_add_open_no_duplicate(self, store):
        store.load()
        store.add_open("/repo/a")
        store.add_open("/repo/a")
        assert store.get_open_repos() == ["/repo/a"]


class TestJsonRepoStoreCloseRepo:
    def test_close_moves_to_recent_head(self, store):
        store.load()
        store.add_open("/repo/a")
        store.add_open("/repo/b")
        store.close_repo("/repo/a")
        assert store.get_open_repos() == ["/repo/b"]
        assert store.get_recent_repos()[0] == "/repo/a"

    def test_close_active_clears_active(self, store):
        store.load()
        store.add_open("/repo/a")
        store.close_repo("/repo/a")
        assert store.get_active() is None


class TestJsonRepoStoreRecentLimit:
    def test_recent_capped_at_20(self, store):
        store.load()
        for i in range(25):
            store.add_open(f"/repo/{i}")
        for i in range(25):
            store.close_repo(f"/repo/{i}")
        assert len(store.get_recent_repos()) == 20

    def test_recent_excludes_open_repos(self, store, store_path):
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(
            json.dumps(
                {
                    "open": ["/repo/a"],
                    "recent": ["/repo/a", "/repo/b"],
                    "active": "/repo/a",
                }
            )
        )
        store.load()
        assert "/repo/a" not in store.get_recent_repos()
        assert store.get_recent_repos() == ["/repo/b"]


class TestJsonRepoStoreRemoveRecent:
    def test_remove_recent(self, store):
        store.load()
        store.add_open("/repo/a")
        store.close_repo("/repo/a")
        assert "/repo/a" in store.get_recent_repos()
        store.remove_recent("/repo/a")
        assert "/repo/a" not in store.get_recent_repos()


class TestJsonRepoStoreForget:
    def test_forget_removes_from_open_recent_and_active(self, store):
        store.load()
        store.add_open("/repo/a")
        store.add_open("/repo/b")
        store.close_repo("/repo/b")  # /repo/b -> recent
        store.set_active("/repo/a")

        store.forget("/repo/a")
        store.forget("/repo/b")

        assert store.get_open_repos() == []
        assert store.get_recent_repos() == []
        assert store.get_active() is None

    def test_forget_unknown_path_is_noop(self, store):
        store.load()
        store.add_open("/repo/a")
        store.forget("/repo/unknown")
        assert store.get_open_repos() == ["/repo/a"]
        assert store.get_active() == "/repo/a"


class TestJsonRepoStoreSetActive:
    def test_set_active(self, store):
        store.load()
        store.add_open("/repo/a")
        store.add_open("/repo/b")
        store.set_active("/repo/a")
        assert store.get_active() == "/repo/a"


class TestJsonRepoStoreSettings:
    def test_get_returns_default_when_missing(self, store):
        store.load()
        assert store.get_repo_setting("/repo/a", "first_parent", False) is False
        assert store.get_repo_setting("/repo/a", "missing", "fallback") == "fallback"

    def test_set_then_get_roundtrip(self, store):
        store.load()
        store.set_repo_setting("/repo/a", "first_parent", True)
        assert store.get_repo_setting("/repo/a", "first_parent", False) is True

    def test_settings_persist_through_save_and_reload(self, store, store_path):
        store.load()
        store.set_repo_setting("/repo/a", "first_parent", True)
        store.save()
        # Re-instantiate to confirm we read from disk, not memory.
        fresh = JsonRepoStore(store_path)
        fresh.load()
        assert fresh.get_repo_setting("/repo/a", "first_parent", False) is True

    def test_settings_survive_close_repo(self, store):
        store.load()
        store.add_open("/repo/a")
        store.set_repo_setting("/repo/a", "first_parent", True)
        store.close_repo("/repo/a")
        assert store.get_repo_setting("/repo/a", "first_parent", False) is True

    def test_settings_survive_remove_recent(self, store):
        store.load()
        store.add_open("/repo/a")
        store.set_repo_setting("/repo/a", "first_parent", True)
        store.close_repo("/repo/a")
        store.remove_recent("/repo/a")
        assert store.get_repo_setting("/repo/a", "first_parent", False) is True

    def test_old_file_without_settings_key_loads_clean(self, store, store_path):
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(
            json.dumps(
                {
                    "open": [],
                    "recent": [],
                    "active": None,
                }
            )
        )
        store.load()
        assert store.get_repo_setting("/repo/a", "first_parent", False) is False
