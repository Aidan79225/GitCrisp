# Diverged-Branch Graph Load via Merge Base — Design

**Date:** 2026-04-28
**Status:** Proposed

## Goal

When the user single-clicks a branch (or tag) in the sidebar that has diverged from the current HEAD, the graph must render that branch's commit with its lane visually connected back to HEAD's mainline at the merge base. Today, the diverged tip's commit is loaded but its lane appears as an isolated circle with a tiny stub edge, because the merge base is not in the loaded set and the doubling retry only checks for the target oid — not for connectivity.

This spec extends the existing `reload_with_extra_tip` flow with a merge-base lookup and a connectivity gate, so the graph keeps doubling its load until the diverged lane has somewhere to converge — capped to avoid loading an unbounded number of commits.

## Symptom (confirmed)

Empirically reproduced via `_compute_lanes` against a synthetic `[A, B, D]` (HEAD chain `A→B→C`, diverged `D→C`, merge base `C` not loaded):

```
row 0 (A): lane=0 ... edges_out=[(0,0,0)]
row 1 (B): lane=0 has_in=True ... edges_out=[(0,0,0)]
row 2 (D): lane=1 has_in=False lines=[(0,0,0)] edges_in=[] edges_out=[(1,1,1)]
```

Row 2 has D's circle in lane 1 with `edges_out=[(1,1,1)]` (a half-cell stub) and no row below. Visually: the diverged tip floats with no connection to HEAD's lane.

When the merge base IS loaded (`[A, D, B, C]`), row 3 (C) shows `edges_in=[(1, 0, 1)]` — D's lane converges into HEAD's lane diagonally. Clean visual.

The fix is therefore not in the lane algorithm or the delegate; both are already correct. The fix is in the loader: ensure the merge base is in the loaded set before stopping the retry loop.

## Architecture

A new `merge_base(oid_a, oid_b) -> str | None` flows through all four layers (domain port → infrastructure → application query → presentation bus → graph widget). The graph widget tracks a new `_pending_merge_base` alongside `_pending_scroll_oid` and gates the existing scroll-and-finish branch on **both** being loaded.

Dependencies still point inward (presentation → application → domain ← infrastructure). No new abstractions outside the existing port-and-bus pattern.

## Scope

- Add `merge_base` to the `IRepositoryReader` port.
- Implement it in `Pygit2Repository` via `pygit2.Repository.merge_base()`.
- Add a `GetMergeBase` application query that delegates to the port.
- Wire `get_merge_base` onto `QueryBus.from_reader`.
- In `GraphWidget`:
  - Add a `MAX_RELOAD_LIMIT = 2000` module constant.
  - Add a `_pending_merge_base: str | None` instance field.
  - Compute the merge base in `reload_with_extra_tip` before falling through to `reload`.
  - Extend the gate in `_on_reload_done` to require both the target oid and the merge base to be loaded; cap doubling at `MAX_RELOAD_LIMIT`.
- Tests for each new method and the new gate behavior.

## Out of Scope

- Changes to the lane assignment algorithm (`_compute_lanes`) or the lane delegate. They already render correctly when the right commits are loaded.
- A new "branch-focused" view mode (Approach 2 in brainstorming).
- Merge-base-bounded walks via `walker.hide()` (Approach 3) — preserves a smaller delta to the existing code.
- Caching merge-base results across clicks. `pygit2.merge_base` is fast enough for the click frequency this targets.
- Handling stash clicks or search-driven scrolls. Today they use different code paths; if and when they need this fix it is a one-line port.

## Files Changed

| File | Change |
|------|--------|
| `git_gui/domain/ports.py` | Add `merge_base(oid_a, oid_b) -> str | None` to `IRepositoryReader` |
| `git_gui/infrastructure/pygit2/commit_ops.py` | Implement `merge_base` |
| `git_gui/application/queries.py` | Add `GetMergeBase` |
| `git_gui/presentation/bus.py` | Wire `get_merge_base = GetMergeBase(reader)` on `QueryBus.from_reader` |
| `git_gui/presentation/widgets/graph.py` | Add `MAX_RELOAD_LIMIT`, `_pending_merge_base`; modify `reload_with_extra_tip` and `_on_reload_done` |
| `tests/infrastructure/test_reads.py` | New test for `merge_base` against a real temp repo |
| `tests/application/test_queries.py` | New delegation test for `GetMergeBase` |
| `tests/presentation/widgets/test_graph_signals.py` | New tests for retry-until-base-loaded and cap-give-up |

**Untouched:** sidebar wiring (`branch_clicked` and `tag_clicked` already feed `reload_with_extra_tip`), `_compute_lanes`, `GraphLaneDelegate`, working-tree, diff, infrastructure mixins other than `commit_ops`, theme.

## Domain Port

`git_gui/domain/ports.py` — add to `IRepositoryReader`:

```python
def merge_base(self, oid_a: str, oid_b: str) -> str | None: ...
```

Returns the merge-base OID hex string, or `None` when there is no common ancestor or either oid is unknown.

## Infrastructure

`git_gui/infrastructure/pygit2/commit_ops.py` — add a method to `CommitOps`:

```python
def merge_base(self, oid_a: str, oid_b: str) -> str | None:
    try:
        result = self._repo.merge_base(
            pygit2.Oid(hex=oid_a), pygit2.Oid(hex=oid_b)
        )
    except (KeyError, ValueError):
        return None
    return str(result) if result is not None else None
```

`pygit2.Repository.merge_base(a, b)` returns a `pygit2.Oid` for the best common ancestor or `None` when the two oids share no history. `KeyError` covers "oid not in repo"; `ValueError` covers malformed hex. Both translate to `None` so the caller can skip the merge-base gate.

## Application Query

`git_gui/application/queries.py` — add alongside `GetCommitGraph`:

```python
@dataclass
class GetMergeBase:
    _reader: IRepositoryReader

    def execute(self, oid_a: str, oid_b: str) -> str | None:
        return self._reader.merge_base(oid_a, oid_b)
```

## Bus

`git_gui/presentation/bus.py` — extend the `QueryBus.from_reader` constructor to also build `GetMergeBase` and assign it to the `get_merge_base` field on the bus. Add `get_merge_base: GetMergeBase` to the `QueryBus` dataclass alongside the existing fields.

## Graph Widget

`git_gui/presentation/widgets/graph.py` —

**1. Module constant** (near `PAGE_SIZE = 50`):

```python
MAX_RELOAD_LIMIT = 2000  # cap the doubling retry to avoid unbounded loads
```

**2. Instance field** (in `__init__`, near `self._pending_scroll_oid`):

```python
self._pending_merge_base: str | None = None
```

**3. `reload_with_extra_tip`** — replace the body so the merge-base is computed before the reload is queued:

```python
def reload_with_extra_tip(self, oid: str) -> None:
    """Reload graph including the given oid as an extra walker tip, then scroll
    to it. For diverged tips, also load down to the merge base with HEAD so the
    lane converges into HEAD's mainline visually."""
    # Already loaded — fast path, no reload.
    for row in range(self._model.rowCount()):
        if self._model.data(self._model.index(row, 0), Qt.UserRole) == oid:
            self.scroll_to_oid(oid, select=True)
            return

    # Compute merge base with HEAD so the doubling retry knows when to stop.
    merge_base: str | None = None
    if self._queries is not None:
        head_oid = self._queries.get_head_oid.execute() or ""
        if head_oid and head_oid != oid:
            try:
                merge_base = self._queries.get_merge_base.execute(head_oid, oid)
            except Exception:
                merge_base = None

    self._pending_scroll_oid = oid
    self._pending_merge_base = merge_base
    self.reload(extra_tips=[oid])
```

**4. `_on_reload_done` — replace the existing `if self._pending_scroll_oid:` block** at `graph.py:392-411` with the merge-base-aware gate:

```python
if self._pending_scroll_oid:
    loaded_oids = {
        self._model.data(self._model.index(r, 0), Qt.UserRole)
        for r in range(self._model.rowCount())
    }
    target_loaded = self._pending_scroll_oid in loaded_oids
    base_loaded = (
        self._pending_merge_base is None
        or self._pending_merge_base in loaded_oids
    )
    if target_loaded and base_loaded:
        self.scroll_to_oid(self._pending_scroll_oid, select=True)
        self._pending_scroll_oid = None
        self._pending_merge_base = None
    elif self._has_more and self._reload_limit < MAX_RELOAD_LIMIT:
        oid = self._pending_scroll_oid
        tips = self._extra_tips
        new_limit = min(self._reload_limit * 2, MAX_RELOAD_LIMIT)
        self._loading = False
        self.reload(extra_tips=tips, limit=new_limit)
    else:
        # No more commits OR cap reached — accept partial result.
        self._pending_scroll_oid = None
        self._pending_merge_base = None
```

The existing branch that triggers the deferred search (`if self._pending_search:`) stays untouched below this block.

## Edge Cases

| Case | Behavior |
|---|---|
| HEAD unborn (empty repo) | `head_oid == ""`, merge-base lookup is skipped, `_pending_merge_base = None`, gate degrades to target-only — same as today. |
| Click on the branch that already equals HEAD | `head_oid == oid`, merge-base skipped, the fast-path `for row` loop short-circuits since HEAD is always at row 0. |
| `get_merge_base` returns `None` (disjoint histories or unknown oid) | `_pending_merge_base = None`, only target-load is gated. No retries to find a merge base that does not exist. |
| Branch is a strict ancestor of HEAD (no divergence) | Merge base equals the clicked branch tip. Loading the tip ⇒ also loads the merge base ⇒ gate satisfied. |
| Branch is a strict descendant of HEAD (fast-forward) | Merge base equals HEAD's tip; HEAD's tip is row 0 ⇒ always loaded ⇒ gate satisfied immediately. |
| Both branches far apart, cap reached | Falls into the `else` branch: clear pending state, scroll best-effort to the target if loaded. Partial graph view; user can still scroll-to-load more manually. |
| User triggers a second reload while one is in flight | Existing `if self._loading: return` guard at the top of `reload` still applies; the in-flight retry runs to completion before the next click is honored. |
| `get_head_oid` raises | The `head_oid` lookup is in a try-implicit context (already wrapped via `or ""`); the broader `try/except Exception` around `get_merge_base` covers it. Worst case: merge_base = None, target-only gate. |

## Performance

- `pygit2.merge_base` runs in C and walks both histories from each tip until they meet. On real repos it is sub-millisecond for non-trivial divergences and unnoticeable on the click thread (where it currently runs synchronously in `reload_with_extra_tip`).
- The doubling retry doubles `_reload_limit` on each round (50 → 100 → 200 → ... → 2000). Worst case is six retries before hitting the cap.
- The per-retry cost is dominated by `get_commit_graph` (the existing walker call). No new background threads, no new DB calls.

## Testing

**`tests/infrastructure/test_reads.py`** — new test:

- `test_merge_base_returns_common_ancestor` — set up a repo with two diverged branches sharing a known commit; assert `merge_base(tip_a, tip_b) == known_common`.
- `test_merge_base_returns_none_for_disjoint` — two unrelated commits (e.g., a fresh orphan commit) → returns `None`.
- `test_merge_base_returns_none_for_unknown_oid` — pass a malformed/unknown oid → returns `None` (does not raise).

**`tests/application/test_queries.py`** — new delegation test:

- `test_get_merge_base_delegates_to_reader` — mirror the existing pattern for `GetCommitGraph`: stub reader returning `"deadbeef"`, assert `GetMergeBase(reader).execute("a", "b") == "deadbeef"` and `reader.merge_base.assert_called_once_with("a", "b")`.

**`tests/presentation/widgets/test_graph_signals.py`** — extend the existing diverged-aware coverage:

- `test_reload_with_extra_tip_computes_merge_base` — stub `get_head_oid` and `get_merge_base`; click an oid not in the model; assert `_pending_scroll_oid` and `_pending_merge_base` are set, and `reload(extra_tips=[oid])` is called.
- `test_on_reload_done_retries_until_merge_base_loaded` — set `_pending_scroll_oid` and `_pending_merge_base`; emit `_on_reload_done` with commits that include the target but NOT the base, with `_has_more=True`; assert `reload` is called again with double the limit. Then re-emit with both included; assert `scroll_to_oid` is called and pending state is cleared.
- `test_on_reload_done_gives_up_at_cap` — same setup, but progressively double up to `MAX_RELOAD_LIMIT`; assert pending state clears and no infinite retry.
- `test_on_reload_done_clears_pending_when_merge_base_is_none` — `_pending_merge_base = None`, target loaded, `_has_more=True`; assert `scroll_to_oid` is called and no further reload (today's behavior, unchanged).

No changes to `tests/presentation/test_graph_model.py` — the lane algorithm is unchanged.

## Risks

- **Cap reached but merge base unloaded.** User sees a partial graph with the diverged tip floating. Acceptable degradation; same as today's broken state but bounded. Mitigated by the cap value (2000) which is large enough for the vast majority of real divergences.
- **`get_merge_base` runs on the UI thread** inside `reload_with_extra_tip`. Sub-millisecond in practice; acceptable. If telemetry later shows it stalling on huge repos, it can be moved into the worker thread — same shape as the existing `get_commit_graph` call.
- **Retry storm if `_has_more` is misreported.** The doubling cap and the early-exit when target+base are both loaded prevent runaway. The existing `_has_more` semantics are unchanged.
