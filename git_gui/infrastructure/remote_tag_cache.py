from __future__ import annotations
import hashlib
import json
from pathlib import Path


class JsonRemoteTagCache:
    """Persists remote tag names per repo to JSON files."""

    def __init__(self, cache_dir: Path | None = None) -> None:
        self._dir = cache_dir or Path.home() / ".gitcrisp" / "remote_tags"

    def _repo_file(self, repo_path: str) -> Path:
        repo_id = hashlib.sha256(repo_path.encode()).hexdigest()[:16]
        return self._dir / f"{repo_id}.json"

    def load(self, repo_path: str) -> dict[str, list[str]]:
        path = self._repo_file(repo_path)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def save(self, repo_path: str, data: dict[str, list[str]]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._repo_file(repo_path)
        path.write_text(json.dumps(data), encoding="utf-8")
