# Tag Support Design

## Overview

Add tag support across the entire UI: sidebar listing, badge display on commit graph and commit detail, and create/delete/push operations.

## Domain & Application Layer

### New Entity: `Tag`

```python
@dataclass
class Tag:
    name: str
    target_oid: str
    is_annotated: bool
    message: str | None
    tagger: str | None
    timestamp: datetime | None
```

### Ports

Add to `IRepositoryReader`:
- `get_tags() -> list[Tag]`

Add to `IRepositoryWriter`:
- `create_tag(name: str, oid: str, message: str | None = None) -> None`
- `delete_tag(name: str) -> None`
- `push_tag(remote: str, name: str) -> None`

### Queries & Commands

- `GetTags` query — calls `reader.get_tags()`
- `CreateTag` command — calls `writer.create_tag(name, oid, message)`
- `DeleteTag` command — calls `writer.delete_tag(name)`
- `PushTag` command — calls `writer.push_tag(remote, name)`

### Infrastructure (`Pygit2Repository`)

- `get_tags()`: iterate `self._repo.references` matching `refs/tags/*`. For each ref, resolve the target. If the target is a Tag object (annotated), extract message/tagger/timestamp. If it's a Commit (lightweight), store with `is_annotated=False`.
- `create_tag()`: if message is provided, use `self._repo.create_tag()` for annotated tag. If message is None/empty, use `self._repo.references.create()` for lightweight tag.
- `delete_tag()`: delete the `refs/tags/<name>` reference.
- `push_tag()`: follow existing push pattern used for branches.

## Badge Display (Graph + Commit Detail)

### Tag Identification

Tags are added to the `refs` dict (which maps `oid -> list[str]`) with a `tag:` prefix. Example: `tag:v1.0.0`.

### Badge Color

In `ref_badge_delegate.py`, extend `_badge_color()`:
- Names starting with `tag:` get purple `#a371f7`.
- When rendering, strip the `tag:` prefix — display `v1.0.0`, not `tag:v1.0.0`.

### Graph Reload Changes

- Background thread additionally calls `get_tags.execute()`.
- When building the `refs` dict, add `tag:{name}` entries alongside branch entries.
- `GraphModel`, `CommitInfo`, `CommitInfoDelegate` require no changes — they already handle arbitrary ref name lists.

### Commit Detail

No changes needed. `set_commit(commit, refs)` already receives and renders ref badges. Tags will appear automatically once they're in the `refs` list.

## Sidebar Tags Section

### Position

New "TAGS" section placed after STASHES. Order: Local Branches → Remote Branches → Stashes → Tags.

### Display

Each tag shows its name (without `refs/tags/` prefix). Clicking a tag emits `tag_clicked` with `target_oid`, scrolling the graph to the tagged commit and showing its detail.

### Context Menu

- **Delete Tag** — deletes the local tag
- **Push Tag** — pushes tag to origin

### Reload

Sidebar reload calls `get_tags.execute()` in the same background thread as branches and stashes.

### New Signals

- `tag_clicked(str)` — emits target_oid
- `tag_delete_requested(str)` — emits tag name
- `tag_push_requested(str)` — emits tag name

## Graph Right-Click: Create Tag

### Context Menu

Add "Create Tag..." option to the commit graph right-click menu, alongside the existing "Create Branch..." option.

### CreateTagDialog

New dialog with:
- **Tag name** field (required) — validated for non-empty, no spaces or illegal characters
- **Message** field (optional, QLineEdit or QTextEdit) — if filled, creates annotated tag; if empty, creates lightweight tag
- **Create** / **Cancel** buttons

### Signal Flow

1. Right-click commit → select "Create Tag..."
2. Graph emits `create_tag_requested(str)` with commit OID
3. MainWindow receives signal → opens `CreateTagDialog`
4. User fills in name (+ optional message), clicks Create
5. MainWindow calls `commands.create_tag.execute(name, oid, message)`
6. On success, `_reload()` refreshes sidebar + graph

## Bus Integration

Add to `QueryBus`:
- `get_tags: GetTags`

Add to `CommandBus`:
- `create_tag: CreateTag`
- `delete_tag: DeleteTag`
- `push_tag: PushTag`

Update `QueryBus.from_reader()` and `CommandBus.from_writer()` factory methods accordingly.

## MainWindow Wiring

New signal connections:
- `sidebar.tag_clicked` → `graph.reload_with_extra_tip` (scroll to tagged commit)
- `sidebar.tag_delete_requested` → handler that calls `commands.delete_tag.execute()` then `_reload()`
- `sidebar.tag_push_requested` → handler that calls `commands.push_tag.execute()` (background thread) then `_reload()`
- `graph.create_tag_requested` → handler that opens `CreateTagDialog`, on accept calls `commands.create_tag.execute()` then `_reload()`
