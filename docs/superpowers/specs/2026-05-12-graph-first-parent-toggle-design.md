# Graph view toggle — first-parent only

## Context

The graph currently always walks the full DAG: every parent of every reachable commit is drawn, so merge commits visibly fan out into the side branches they pulled in. When a repo has frequent merges from feature branches, this is the dominant visual noise — the user can't quickly see "what happened on this line of development" without manually tracing through side branches.

The user wants a toggle on the graph that switches it into a `git log --first-parent` style view: walking from HEAD (and any pushed extra tips), only `parent[0]` of each commit is followed. Side-branch commits don't appear in the list at all; merge commits stay as single rows with no inbound merge line. The toggle's state is per-repo — different repos have different "right" defaults, and the user shouldn't have to re-toggle on every repo switch.

The mechanism already exists at the pygit2 layer (`walker.simplify_first_parent()` is used in `get_commit_range`); this design wires it through to the graph view and gives it a persisted UI control.

## Scope

In scope:
- A checkable toggle button in the graph widget's header bar.
- Threading a `first_parent` kwarg through the data layer (port → application → infrastructure).
- Persisting the toggle per-repo in `JsonRepoStore` via a new generic `settings` dict.
- Per-repo `set_repo_setting` / `get_repo_setting` accessors on `IRepoStore`.
- A new SVG icon for the toggle.

Out of scope:
- Other view modes (date-ordered, no-merges only, etc.) — not asked for and not designed for in advance, though the generic `settings` dict leaves room.
- Per-repo settings UI surface beyond this one toggle.
- Any change to `get_commit_range`, `get_commit_files`, or other commit-walking code paths — they already do the right thing.

## Mode semantics

When `first_parent=True`:
- `pygit2.Repository.walk(...)` is called as today and the resulting walker has `simplify_first_parent()` invoked before iteration.
- For each pushed tip (HEAD, optional upstream, optional caller-supplied `extra_tips`), only `parent[0]` is followed.
- Merge commits themselves remain in the listing (matching `git log --first-parent`). Only the commits that were brought in by the merge disappear.
- Combines naturally with `extra_tips`: clicking a side branch in the sidebar pushes its tip onto the walker; `simplify_first_parent()` reduces both lines (HEAD's and the pushed tip's) to first-parent ancestry, converging at the merge-base.
- Pagination (`skip`) is unaffected — every `get_commits` call constructs a fresh walker and reapplies the flag.

When `first_parent=False`:
- Behavior is identical to today (no walker simplification).

## Architecture

### Data layer

Three layers, one new keyword-only argument with default `False`:

1. **Port** (`git_gui/domain/ports.py`)
   ```python
   class IRepositoryReader(Protocol):
       def get_commits(
           self,
           limit: int,
           skip: int = 0,
           extra_tips: list[str] | None = None,
           *,
           first_parent: bool = False,
       ) -> list[Commit]: ...
   ```

2. **Application** (`git_gui/application/queries.py`)
   ```python
   class GetCommitGraph:
       def execute(
           self,
           limit: int = 200,
           skip: int = 0,
           extra_tips: list[str] | None = None,
           *,
           first_parent: bool = False,
       ) -> list[Commit]:
           return self._reader.get_commits(
               limit, skip, extra_tips=extra_tips, first_parent=first_parent,
           )
   ```

3. **Infrastructure** (`git_gui/infrastructure/pygit2/commit_ops.py`)
   In `CommitOps.get_commits`, after the walker is created and tips are pushed (existing code), call `walker.simplify_first_parent()` when `first_parent` is `True`, then proceed with the existing `skip` / `limit` iteration.

### Persistence layer

`JsonRepoStore` (`git_gui/infrastructure/repo_store.py`) gains a per-repo settings dict so this isn't a single-purpose bolt-on.

**On-disk JSON shape (additive):**
```json
{
  "open": [...],
  "recent": [...],
  "active": "...",
  "settings": {
    "/path/to/repo": { "first_parent": true }
  }
}
```

Older `repos.json` files without a `"settings"` key load with `_settings = {}` — fully backwards-compatible.

**Port additions** (`IRepoStore` in `git_gui/domain/ports.py`):
```python
def get_repo_setting(self, path: str, key: str, default=None) -> object: ...
def set_repo_setting(self, path: str, key: str, value) -> None: ...
```

Generic key/value because the only consumer (the graph toggle) doesn't justify a typed wrapper, and the next per-repo setting that arrives gets to reuse the same plumbing.

**Lifecycle:** settings persist even when a repo is closed or removed from the recent list. They're cheap and a user re-opening the same path should find their view intact. No automatic pruning — if it ever bothers anyone, we add a `prune_orphan_settings()` later.

### Presentation layer

`GraphWidget` (`git_gui/presentation/widgets/graph.py`):

- **New constructor argument:** `repo_store: IRepoStore` — passed through `MainWindow._build_widgets`. The widget reads/writes the persisted setting directly rather than going through a callback, mirroring how `WorkingTreeWidget` reaches for `repo_path`.
- **New state:** `self._first_parent: bool = False` (default until `set_repo_path` is called).
- **New method:** `set_repo_path(path: str | None) -> None`
  - If `path` is `None`: `self._first_parent = False` and uncheck the button silently.
  - Otherwise: read `repo_store.get_repo_setting(path, "first_parent", False)`, update `self._first_parent`, and sync the button's checked state silently (no reload — `set_buses` is about to reload anyway).
- **New button** in the header bar, added between the Insight button and the existing stretch:
  - `QPushButton` with `setCheckable(True)`, 36×36, tooltip `"Show first-parent history only"`.
  - Themed via the existing `_tinted_button_icons` pipeline (icon name `"ic_first_parent"`).
  - `toggled(bool)` connects to a handler that:
    1. Updates `self._first_parent`.
    2. Calls `self._repo_store.set_repo_setting(self._repo_path, "first_parent", checked)` and `save()` — guarded by `self._repo_path is not None`.
    3. Calls `self.reload()` to refresh with the new flag.
- **`reload()` and `_on_scroll`:** pass `first_parent=self._first_parent` to `queries.get_commit_graph.execute(...)` at both call sites currently using `get_commit_graph.execute`.
- **`set_buses(queries, commands)`:** unchanged behaviorally; the per-repo setting is loaded by the earlier `set_repo_path` call.

`MainWindow` (`git_gui/presentation/main_window/main_window.py`):
- `_build_widgets` passes `self._repo_store` into `GraphWidget(...)`.
- After construction, calls `self._graph.set_repo_path(self._repo_path)` so the initial render uses the persisted setting.

`RepoLifecycleMixin` (`git_gui/presentation/main_window/repo_lifecycle.py`):
- `_on_repo_ready`: call `self._graph.set_repo_path(path)` before `self._graph.set_buses(...)`.
- `_enter_empty_state`: call `self._graph.set_repo_path(None)`.

### Icon

New file `arts/ic_first_parent.svg` — a 24×24 glyph showing a single vertical mainline with a faint stub branching off and stopping (conveying "side branch elided"). Single-color SVG so the existing `_tinted_icon` pipeline can recolor it for light/dark themes. The placeholder draft will be:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <line x1="8" y1="3" x2="8" y2="21" />
  <circle cx="8" cy="6" r="1.6" fill="currentColor"/>
  <circle cx="8" cy="12" r="1.6" fill="currentColor"/>
  <circle cx="8" cy="18" r="1.6" fill="currentColor"/>
  <path d="M8 12 C 13 12, 14 9, 16 8" stroke-opacity="0.35"/>
  <circle cx="16" cy="8" r="1.4" stroke-opacity="0.35"/>
</svg>
```

Reads at a glance as "main line + faded sibling." Final tweaks during implementation.

## Interactions

- **Sidebar branch/tag click (push extra tip):** No special-case. The pushed tip is added to the walker before `simplify_first_parent()`, so both the HEAD line and the side branch line are reduced to first-parent ancestry and converge at the merge-base.
- **Pagination on scroll:** Each `get_commits(skip=...)` builds a new walker and reapplies the flag. No persisted walker state.
- **Ctrl+F search:** Searches only loaded rows (first-parent-only in this mode). Naturally bounded; no code change required.
- **Repo switch:** `_on_repo_ready` calls `set_repo_path(path)` *before* `set_buses(...)`, so the first reload after a switch already reflects the persisted setting. No flash of the wrong mode.
- **Empty state:** `set_repo_path(None)` resets the toggle to unchecked.
- **`set_buses(None, None)` (no repo):** `set_repo_path(None)` is called separately by the empty-state path, so the button stays off.

## Testing

Three layers of tests:

### Infrastructure — `tests/infrastructure/test_reads.py`

New test creating a tiny temp pygit2 repo:
- Commit A on master.
- Branch to `feature`, two commits B and C on `feature`.
- Switch back to master, commit D.
- Merge `feature` into master, producing merge commit M (parents `[D, C]`).

Assertions:
- `get_commits(limit=100, first_parent=False)` → set includes `{A, B, C, D, M}`.
- `get_commits(limit=100, first_parent=True)` → set is `{A, D, M}` (no side-branch commits).
- Pagination test: `get_commits(limit=2, skip=1, first_parent=True)` returns the next two from the first-parent line, never a side-branch commit.

### Repo store — `tests/infrastructure/test_repo_store.py`

Round-trip tests:
- `set_repo_setting("/p", "first_parent", True)` → `save()` → re-instantiate from the same path → `get_repo_setting("/p", "first_parent", False) is True`.
- Missing key returns `default`.
- Settings survive `close_repo` (path moves to recent, but setting stays).
- Settings survive `remove_recent`.
- Old `repos.json` without a `"settings"` key loads cleanly (treated as `{}`).

### Widget — `tests/presentation/widgets/test_graph_first_parent.py` (new file)

Minimal test, similar in shape to `test_working_tree_banner.py`'s `_make_widget` style (bypass full `__init__`, supply mocks):
- Construct a widget with a mock `repo_store` (configured to return `False` from `get_repo_setting`) and a mock `queries`.
- Call `set_repo_path("/p")` → assert `_first_parent` is `False`.
- Toggle the button to checked → assert `repo_store.set_repo_setting("/p", "first_parent", True)` was called and `save()` was called.
- Assert `queries.get_commit_graph.execute` was called with `first_parent=True` after the toggle.
- Repeat with `repo_store.get_repo_setting` configured to return `True` and verify the button initializes checked.

### Suite

Full `uv run pytest tests/ -q` must remain green (currently 683; the new tests should bring it to ~691).

## Files touched

| File | Change |
|------|--------|
| `git_gui/domain/ports.py` | `IRepositoryReader.get_commits` gets keyword-only `first_parent=False`. `IRepoStore` gets `get_repo_setting` / `set_repo_setting`. |
| `git_gui/application/queries.py` | `GetCommitGraph.execute` passes the kwarg through. |
| `git_gui/infrastructure/pygit2/commit_ops.py` | Apply `walker.simplify_first_parent()` when flag set. |
| `git_gui/infrastructure/repo_store.py` | `_settings: dict[str, dict[str, Any]]`; load/save it; `get_repo_setting`/`set_repo_setting`. |
| `git_gui/presentation/widgets/graph.py` | New constructor arg `repo_store`, `_first_parent` state, `set_repo_path`, toggle button + handler, kwarg pass-through to `execute` at both call sites. |
| `git_gui/presentation/main_window/main_window.py` | Pass `repo_store` into `GraphWidget`; call `set_repo_path` after construction. |
| `git_gui/presentation/main_window/repo_lifecycle.py` | Call `_graph.set_repo_path(path)` in `_on_repo_ready` and `_enter_empty_state`. |
| `arts/ic_first_parent.svg` | New icon (draft in this doc). |
| `tests/infrastructure/test_reads.py` | New tests for `get_commits(first_parent=...)`. |
| `tests/infrastructure/test_repo_store.py` | New tests for per-repo settings. |
| `tests/presentation/widgets/test_graph_first_parent.py` | New file — widget behavior tests. |

## Open questions

None blocking. Icon style is a draft; final glyph can be tweaked during implementation without affecting the design.
