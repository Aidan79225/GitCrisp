from __future__ import annotations
import json
from pathlib import Path

_RECENT_LIMIT = 20


class JsonRepoStore:
    """Persists open/recent repo lists to a JSON file."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or Path.home() / ".gitcrisp" / "repos.json"
        self._open: list[str] = []
        self._recent: list[str] = []
        self._active: str | None = None

    def load(self) -> None:
        if self._path.exists():
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._open = list(data.get("open", []))
            self._recent = list(data.get("recent", []))
            self._active = data.get("active")
        else:
            self._open = []
            self._recent = []
            self._active = None

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"open": self._open, "recent": self._recent, "active": self._active}
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def get_open_repos(self) -> list[str]:
        return list(self._open)

    def get_recent_repos(self) -> list[str]:
        return [r for r in self._recent if r not in self._open]

    def get_active(self) -> str | None:
        return self._active

    def add_open(self, path: str) -> None:
        if path in self._open:
            self._open.remove(path)
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

    def set_active(self, path: str) -> None:
        self._active = path
