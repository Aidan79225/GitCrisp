from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_RECENT_LIMIT = 20


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _replace_file(path: Path, text: str) -> None:
    # Write a sibling file and swap it in, so a crash, power loss or full disk
    # mid-write leaves the previous file whole rather than truncated.
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


class JsonRepoStore:
    """Persists open/recent repo lists and per-repo settings to a JSON file."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or Path.home() / ".gitcrisp" / "repos.json"
        self._open: list[str] = []
        self._recent: list[str] = []
        self._active: str | None = None
        self._settings: dict[str, dict[str, Any]] = {}

    def load(self) -> None:
        data = self._read_file()
        self._open = _str_list(data.get("open"))
        self._recent = _str_list(data.get("recent"))
        active = data.get("active")
        self._active = active if isinstance(active, str) else None
        raw_settings = data.get("settings")
        if not isinstance(raw_settings, dict):
            raw_settings = {}
        self._settings = {str(k): dict(v) for k, v in raw_settings.items() if isinstance(v, dict)}

    def _read_file(self) -> dict[str, Any]:
        # A crash mid-save or a hand edit can leave the file unreadable; the
        # app must still start, so fall back to an empty store.
        if not self._path.exists():
            return {}
        try:
            # utf-8-sig: editors such as Notepad may add a BOM on save.
            data = json.loads(self._path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as e:
            logger.warning("Could not read %s: %s; starting with no repos", self._path, e)
            return {}
        if not isinstance(data, dict):
            logger.warning("Ignoring %s: its root is not an object", self._path)
            return {}
        return data

    def save(self) -> None:
        """Write the store to disk, raising OSError when the write fails.

        The caller is the one that can tell the user; the in-memory state stays
        current either way, so the next save tries again.
        """
        data = {
            "open": self._open,
            "recent": self._recent,
            "active": self._active,
            "settings": self._settings,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        _replace_file(self._path, json.dumps(data, indent=2))

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
