from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_RECENT_LIMIT = 20


class JsonRepoStore:
    """Persists open/recent repo lists and per-repo settings to a JSON file."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or Path.home() / ".gitcrisp" / "repos.json"
        self._open: list[str] = []
        self._recent: list[str] = []
        self._active: str | None = None
        self._settings: dict[str, dict[str, Any]] = {}

    def load(self) -> None:
        if self._path.exists():
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._open = list(data.get("open", []))
            self._recent = list(data.get("recent", []))
            self._active = data.get("active")
            raw_settings = data.get("settings", {}) or {}
            self._settings = {
                str(k): dict(v) for k, v in raw_settings.items() if isinstance(v, dict)
            }
        else:
            self._open = []
            self._recent = []
            self._active = None
            self._settings = {}

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "open": self._open,
            "recent": self._recent,
            "active": self._active,
            "settings": self._settings,
        }
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def get_open_repos(self) -> list[str]:
        return list(self._open)

    def get_recent_repos(self) -> list[str]:
        return [r for r in self._recent if r not in self._open]

    def get_active(self) -> str | None:
        return self._active

    def add_open(self, path: str, after: str | None = None) -> None:
        if path in self._open:
            self._open.remove(path)
        if after and after in self._open:
            idx = self._open.index(after) + 1
            self._open.insert(idx, path)
        else:
            self._open.insert(0, path)
        if path in self._recent:
            self._recent.remove(path)
        self._active = path

    def close_repo(self, path: str) -> None:
        if path in self._open:
            self._open.remove(path)
        if path not in self._recent:
            self._recent.insert(0, path)
            self._recent = self._recent[:_RECENT_LIMIT]
        if self._active == path:
            self._active = None

    def remove_recent(self, path: str) -> None:
        if path in self._recent:
            self._recent.remove(path)

    def forget(self, path: str) -> None:
        """Drop a path entirely — from open, recent, and active.

        Unlike close_repo (which demotes an open repo to recent), this fully
        removes a path. Used to prune stored paths that no longer resolve to a
        git repository (e.g. a deleted worktree) so they stop reappearing.
        """
        if path in self._open:
            self._open.remove(path)
        if path in self._recent:
            self._recent.remove(path)
        if self._active == path:
            self._active = None

    def set_active(self, path: str) -> None:
        self._active = path

    def set_open_order(self, paths: list[str]) -> None:
        """Replace the open repos list with a new ordering."""
        self._open = list(paths)

    def get_repo_setting(self, path: str, key: str, default: Any = None) -> Any:
        return self._settings.get(path, {}).get(key, default)

    def set_repo_setting(self, path: str, key: str, value: Any) -> None:
        self._settings.setdefault(path, {})[key] = value
