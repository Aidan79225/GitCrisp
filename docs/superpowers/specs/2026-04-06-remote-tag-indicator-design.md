# Remote Tag Indicator Design

## Overview

Show a cloud icon (`arts/ic_cloud_done.svg`) next to tags in the sidebar that exist on the remote. Remote tag info is fetched during fetch operations and cached to `~/.gitcrisp/` for persistence across sessions.

## Remote Tag Cache

### Storage

- **Location:** `~/.gitcrisp/remote_tags/{repo_id}.json`
- **repo_id:** SHA-256 hash of the repo's absolute workdir path (avoids path separator / length issues)
- **Format:**
```json
{
  "origin": ["v1.0.0", "v2.0.0"]
}
```

### Interface

New protocol in `ports.py`:

```python
class IRemoteTagCache(Protocol):
    def load(self, repo_path: str) -> dict[str, list[str]]: ...
    def save(self, repo_path: str, data: dict[str, list[str]]) -> None: ...
```

### Implementation

`JsonRemoteTagCache` in `git_gui/infrastructure/remote_tag_cache.py`:
- `load()`: read JSON file, return empty dict if file doesn't exist
- `save()`: write JSON file, create directory if needed

## Getting Remote Tags

### Infrastructure

Add `get_remote_tags(remote: str) -> list[str]` to `IRepositoryReader` and `Pygit2Repository`:
- Runs `git ls-remote --tags <remote>`
- Parses output to extract tag names (strip `refs/tags/` prefix, skip `^{}` dereferenced entries)
- Returns list of tag name strings

## Sidebar Icon Display

### Data flow

1. Sidebar reload worker reads cache file via `IRemoteTagCache.load()`
2. Extracts a flat `set[str]` of all remote tag names (across all remotes)
3. Passes `remote_tag_names` to `_on_load_done`
4. When building TAGS section items, if tag name is in the remote set → `child.setIcon(QIcon("arts/ic_cloud_done.svg"))`

### Signal change

`_LoadSignals.done` gains a 4th parameter: `Signal(list, list, list, set)` — branches, stashes, tags, remote_tag_names.

### Dependencies

- Sidebar needs access to `IRemoteTagCache` (passed via constructor or bus)
- Cache is read in the background thread (IO), not on main thread

## Fetch → Cache Update

### Trigger

All fetch operations: single-remote fetch, fetch all --prune.

### Flow

1. Fetch worker completes the fetch operation
2. Same worker then calls `get_remote_tags(remote)` (or for fetch-all, query "origin")
3. Worker saves result via `cache.save(repo_path, data)`
4. Worker emits finished signal → `_reload()` → sidebar reads updated cache → icons update

### Integration

The fetch operations run in `MainWindow._run_remote_op()`. The worker function needs access to `get_remote_tags` and the cache. This means:
- Add `get_remote_tags` to the port/query layer
- The fetch handlers in MainWindow wrap the fetch + cache-update into a single worker function
- No new signals needed — existing `_on_remote_done → _reload()` handles the UI refresh

## Files Affected

| File | Action | Responsibility |
|------|--------|----------------|
| `git_gui/domain/ports.py` | Modify | Add `IRemoteTagCache` protocol, add `get_remote_tags` to `IRepositoryReader` |
| `git_gui/infrastructure/remote_tag_cache.py` | Create | JSON cache read/write |
| `git_gui/infrastructure/pygit2_repo.py` | Modify | Implement `get_remote_tags` |
| `git_gui/application/queries.py` | Modify | Add `GetRemoteTags` query |
| `git_gui/presentation/bus.py` | Modify | Add `get_remote_tags` to QueryBus |
| `git_gui/presentation/widgets/sidebar.py` | Modify | Accept cache, show icon on remote tags |
| `git_gui/presentation/main_window.py` | Modify | Pass cache to sidebar, update cache after fetch |
| `main.py` | Modify | Create cache instance and pass through |
