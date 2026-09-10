# Diverged-Branch Graph Load via Merge Base — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the user single-clicks a diverged branch (or tag) in the sidebar, the graph reloads with enough commits that the diverged lane converges into HEAD's mainline at the merge base, instead of rendering as an isolated floating circle.

**Architecture:** Add a `merge_base(oid_a, oid_b) -> str | None` through all four layers (port → infrastructure → application query → bus). In `GraphWidget.reload_with_extra_tip`, look up the merge base with HEAD before triggering the reload; in `_on_reload_done`, gate the "scroll-and-finish" branch on **both** the target oid and the merge base being loaded. The doubling retry continues until both are loaded, capped at a new `MAX_RELOAD_LIMIT = 2000`.

**Tech Stack:** Python 3.13, PySide6, pygit2 (`Repository.merge_base`), pytest, pytest-qt, uv.

**Spec:** `docs/superpowers/specs/2026-04-28-diverged-branch-merge-base-load-design.md`

---

## File Map

| Path | Action |
|------|--------|
| `git_gui/domain/ports.py` | Modify — add `merge_base` to `IRepositoryReader` |
| `git_gui/infrastructure/pygit2/commit_ops.py` | Modify — add `merge_base` method to `CommitOps` |
| `git_gui/application/queries.py` | Modify — add `GetMergeBase` query class |
| `git_gui/presentation/bus.py` | Modify — wire `get_merge_base` onto `QueryBus` |
| `git_gui/presentation/widgets/graph.py` | Modify — add `MAX_RELOAD_LIMIT`, `_pending_merge_base`; update `reload_with_extra_tip` and `_on_reload_done` |
| `tests/infrastructure/test_reads.py` | Modify — add three `merge_base` tests |
| `tests/application/test_queries.py` | Modify — add `GetMergeBase` delegation test |
| `tests/presentation/widgets/test_graph_signals.py` | Modify — add four tests for the new behavior |

Untouched: domain entities, `_compute_lanes`, `GraphLaneDelegate`, sidebar, working-tree, diff, theme, infrastructure mixins other than `commit_ops`.

---

## Task 1: Add `merge_base` to domain port + infrastructure

**Files:**
- Modify: `git_gui/domain/ports.py`
- Modify: `git_gui/infrastructure/pygit2/commit_ops.py`
- Test: `tests/infrastructure/test_reads.py`

This task adds the bottom layer of the new method — the port declaration and the pygit2 implementation — with infrastructure tests. After this commit the application layer cannot yet reach the new method.

- [ ] **Step 1: Write the failing test (common-ancestor case)**

Open `tests/infrastructure/test_reads.py`. Add this test at the end of the file:

```python
def test_merge_base_returns_common_ancestor(repo_path, repo_impl):
    """Two diverged branches share their initial commit as merge base."""
    repo = pygit2.Repository(str(repo_path))
    sig = pygit2.Signature("T", "t@t.com")
    base_oid = repo.head.target  # initial commit on master

    # Branch "feat" off master, add commit A
    repo.branches.local.create("feat", repo.head.peel())
    (repo_path / "a.txt").write_text("a")
    repo.index.add("a.txt")
    repo.index.write()
    tree_a = repo.index.write_tree()
    a_oid = repo.create_commit("refs/heads/feat", sig, sig, "A", tree_a, [base_oid])

    # Add commit B onto master
    (repo_path / "b.txt").write_text("b")
    repo.index.read()
    repo.index.add("b.txt")
    repo.index.write()
    tree_b = repo.index.write_tree()
    b_oid = repo.create_commit("refs/heads/master", sig, sig, "B", tree_b, [base_oid])

    impl = Pygit2Repository(str(repo_path))
    result = impl.merge_base(str(a_oid), str(b_oid))
    assert result == str(base_oid)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/infrastructure/test_reads.py::test_merge_base_returns_common_ancestor -v`

Expected: FAIL with `AttributeError: 'Pygit2Repository' object has no attribute 'merge_base'`.

- [ ] **Step 3: Add `merge_base` to the `IRepositoryReader` Protocol**

Open `git_gui/domain/ports.py`. Find the `class IRepositoryReader(Protocol):` block. After the line `def get_commit_range(self, head_oid: str, base_oid: str) -> list[Commit]: ...` (the last method in the protocol), add:

```python
    def merge_base(self, oid_a: str, oid_b: str) -> str | None: ...
```

The full updated last few lines of the protocol should read:

```python
    def get_commit_range(self, head_oid: str, base_oid: str) -> list[Commit]: ...
    def merge_base(self, oid_a: str, oid_b: str) -> str | None: ...
```

- [ ] **Step 4: Implement `merge_base` in `CommitOps`**

Open `git_gui/infrastructure/pygit2/commit_ops.py`. Locate the `get_commit_range` method (after `get_commit`). After it, add:

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

`pygit2.Repository.merge_base(a, b)` returns a `pygit2.Oid` for the best common ancestor or `None` when the two oids share no history. `KeyError` covers "oid not in repo"; `ValueError` covers malformed hex. Both translate to `None`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/infrastructure/test_reads.py::test_merge_base_returns_common_ancestor -v`

Expected: PASS.

- [ ] **Step 6: Add the disjoint-history test**

Append to `tests/infrastructure/test_reads.py`:

```python
def test_merge_base_returns_none_for_disjoint(repo_path, repo_impl):
    """Two unrelated commits (orphan branch) have no merge base."""
    repo = pygit2.Repository(str(repo_path))
    sig = pygit2.Signature("T", "t@t.com")
    head_oid = repo.head.target

    # Create an orphan branch (a fresh commit with no parents)
    (repo_path / "orphan.txt").write_text("orphan")
    repo.index.read(force=True)
    repo.index.clear()
    repo.index.add("orphan.txt")
    repo.index.write()
    tree = repo.index.write_tree()
    orphan_oid = repo.create_commit(
        "refs/heads/orphan", sig, sig, "orphan", tree, []
    )

    impl = Pygit2Repository(str(repo_path))
    assert impl.merge_base(str(head_oid), str(orphan_oid)) is None
```

- [ ] **Step 7: Add the unknown-oid test**

Append to `tests/infrastructure/test_reads.py`:

```python
def test_merge_base_returns_none_for_unknown_oid(repo_impl):
    """Malformed or unknown oids yield None instead of raising."""
    # Valid format but not in repo
    bogus = "0" * 40
    real = repo_impl.get_commits(limit=1)[0].oid
    assert repo_impl.merge_base(real, bogus) is None
    # Malformed hex — too short
    assert repo_impl.merge_base(real, "abc") is None
```

- [ ] **Step 8: Run the three new tests**

Run: `uv run pytest tests/infrastructure/test_reads.py -k merge_base -v`

Expected: 3 passed.

- [ ] **Step 9: Run the full test suite to verify no regressions**

Run: `uv run pytest tests/ 2>&1 | tail -3`

Expected: all tests pass (533 if starting from the post-merge baseline of 530, +3 new).

- [ ] **Step 10: Commit**

```bash
git add git_gui/domain/ports.py git_gui/infrastructure/pygit2/commit_ops.py tests/infrastructure/test_reads.py
git commit -m "$(cat <<'EOF'
feat(infra): add merge_base to IRepositoryReader and Pygit2Repository

Wraps pygit2.Repository.merge_base to return the best common ancestor
oid as a hex string, or None when the histories are disjoint or either
oid is unknown. Used by the upcoming graph-load fix for diverged
branches — the loader needs to know when it has loaded enough commits
for the diverged lane to converge into HEAD's mainline.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds.

---

## Task 2: Add `GetMergeBase` application query

**Files:**
- Modify: `git_gui/application/queries.py`
- Test: `tests/application/test_queries.py`

Adds the application-layer wrapper that delegates to the port. After this commit the presentation layer still cannot reach the query — that wiring is Task 3.

- [ ] **Step 1: Write the failing delegation test**

Open `tests/application/test_queries.py`. Add at the top, alongside the existing `from git_gui.application.queries import (...)` block, the new symbol:

Find:
```python
from git_gui.application.queries import (
    GetCommitGraph, GetBranches, GetCommitFiles,
    GetFileDiff, GetWorkingTree, GetStashes,
)
```

Replace with:
```python
from git_gui.application.queries import (
    GetCommitGraph, GetBranches, GetCommitFiles,
    GetFileDiff, GetWorkingTree, GetStashes,
    GetMergeBase,
)
```

Then append at the end of the file:

```python
def test_get_merge_base_delegates_to_reader():
    reader = _reader()
    reader.merge_base.return_value = "deadbeef"
    result = GetMergeBase(reader).execute("aaa", "bbb")
    reader.merge_base.assert_called_once_with("aaa", "bbb")
    assert result == "deadbeef"


def test_get_merge_base_returns_none_when_reader_returns_none():
    reader = _reader()
    reader.merge_base.return_value = None
    result = GetMergeBase(reader).execute("aaa", "bbb")
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/application/test_queries.py -k merge_base -v`

Expected: FAIL with `ImportError: cannot import name 'GetMergeBase' from 'git_gui.application.queries'`.

- [ ] **Step 3: Implement `GetMergeBase`**

Open `git_gui/application/queries.py`. After the `class GetCommitRange:` block (the last query class in the file), append:

```python


class GetMergeBase:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self, oid_a: str, oid_b: str) -> str | None:
        return self._reader.merge_base(oid_a, oid_b)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/application/test_queries.py -k merge_base -v`

Expected: 2 passed.

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest tests/ 2>&1 | tail -3`

Expected: all tests pass (535: +2 new).

- [ ] **Step 6: Commit**

```bash
git add git_gui/application/queries.py tests/application/test_queries.py
git commit -m "$(cat <<'EOF'
feat(application): add GetMergeBase query

Thin delegating wrapper over IRepositoryReader.merge_base, mirroring the
shape of every other query in the module.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds.

---

## Task 3: Wire `get_merge_base` onto `QueryBus`

**Files:**
- Modify: `git_gui/presentation/bus.py`

Adds the new query to the `QueryBus` dataclass and to `from_reader`. No new tests — the bus is exercised end-to-end by every presentation-layer test that runs through it. We just need to confirm the existing suite stays green.

- [ ] **Step 1: Add the import**

Open `git_gui/presentation/bus.py`. Find the import block at the top:

```python
from git_gui.application.queries import (
    GetCommitGraph, GetBranches, GetStashes, GetTags, GetRemoteTags, GetCommitStats,
    GetCommitFiles, GetFileDiff, GetStagedDiff, GetWorkingTree,
    GetCommitDetail, IsDirty, GetHeadOid,
    ListRemotes, ListSubmodules, ListLocalBranchesWithUpstream,
    GetRepoState, IsAncestor, GetMergeAnalysis,
    GetMergeHead, GetMergeMsg, HasUnresolvedConflicts,
    GetCommitDiffMap, GetWorkingTreeDiffMap, GetCommitRange,
)
```

Replace `GetCommitRange,` on the last line of the import with `GetCommitRange, GetMergeBase,` so the block ends:

```python
    GetCommitDiffMap, GetWorkingTreeDiffMap, GetCommitRange, GetMergeBase,
)
```

- [ ] **Step 2: Add the field to `QueryBus`**

Find the `@dataclass class QueryBus:` block. After the line `get_commit_range: GetCommitRange` (the last field), add:

```python
    get_merge_base: GetMergeBase
```

The full tail of the dataclass should read:

```python
    get_commit_diff_map: GetCommitDiffMap
    get_working_tree_diff_map: GetWorkingTreeDiffMap
    get_commit_range: GetCommitRange
    get_merge_base: GetMergeBase
```

- [ ] **Step 3: Wire the construction in `from_reader`**

In the same file, find the `from_reader` classmethod. Find the line `get_commit_range=GetCommitRange(reader),` and add immediately after it:

```python
            get_merge_base=GetMergeBase(reader),
```

The tail of `from_reader` should read:

```python
            get_commit_diff_map=GetCommitDiffMap(reader),
            get_working_tree_diff_map=GetWorkingTreeDiffMap(reader),
            get_commit_range=GetCommitRange(reader),
            get_merge_base=GetMergeBase(reader),
        )
```

- [ ] **Step 4: Run the full test suite**

Run: `uv run pytest tests/ 2>&1 | tail -3`

Expected: all tests pass (still 535 — no test count change, just a structural addition).

If anything fails — most likely a positional-arg construction of `QueryBus(...)` somewhere — fix the call site to use keyword args (everything in the codebase already does, so this should not happen, but if it does, surface it as a concern).

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/bus.py
git commit -m "$(cat <<'EOF'
feat(bus): wire GetMergeBase onto QueryBus.from_reader

Exposes the new merge-base query to presentation-layer widgets via the
standard bus pattern.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds.

---

## Task 4: Add the merge-base lookup in `reload_with_extra_tip`

**Files:**
- Modify: `git_gui/presentation/widgets/graph.py`
- Test: `tests/presentation/widgets/test_graph_signals.py`

This task introduces the new `MAX_RELOAD_LIMIT` constant, the `_pending_merge_base` instance field, and updates `reload_with_extra_tip` to compute the merge base. **The new field is not yet read** in `_on_reload_done` — that's Task 5. After this commit, behavior is unchanged for users; only the internal state changes.

- [ ] **Step 1: Write the failing test for the merge-base lookup**

Open `tests/presentation/widgets/test_graph_signals.py`. Add the following test at the end of the file:

```python
# ── 5. reload_with_extra_tip computes merge base for diverged tips ───────


def test_reload_with_extra_tip_computes_merge_base_for_diverged_tip(qtbot):
    """When the clicked oid is not in the model, look up the merge base
    with HEAD and stash it in _pending_merge_base before triggering reload."""
    w = _make_widget(qtbot, commits=[_make_commit("HEAD")])
    w._pending_merge_base = None

    # Stub queries.
    w._queries.get_head_oid.execute.return_value = "HEAD"
    w._queries.get_merge_base.execute.return_value = "BASE"

    # Spy on reload so we don't need a real worker thread.
    w.reload = MagicMock()

    w.reload_with_extra_tip("DIV")  # not in the model

    w._queries.get_merge_base.execute.assert_called_once_with("HEAD", "DIV")
    assert w._pending_scroll_oid == "DIV"
    assert w._pending_merge_base == "BASE"
    w.reload.assert_called_once_with(extra_tips=["DIV"])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/presentation/widgets/test_graph_signals.py::test_reload_with_extra_tip_computes_merge_base_for_diverged_tip -v`

Expected: FAIL — `_make_widget` does not set `_pending_merge_base` (`AttributeError`), or the assertion `_pending_merge_base == "BASE"` fails because nothing assigns it.

- [ ] **Step 3: Add `MAX_RELOAD_LIMIT` and `_pending_merge_base`**

Open `git_gui/presentation/widgets/graph.py`. Find the line `PAGE_SIZE = 50` near the top of the file. After it, add:

```python
MAX_RELOAD_LIMIT = 2000  # cap doubling retry to avoid unbounded loads
```

Then find `__init__` of `GraphWidget`. Locate the line `self._pending_scroll_oid: str | None = None`. After it, add:

```python
        self._pending_merge_base: str | None = None
```

- [ ] **Step 4: Update `_make_widget` test fixture to initialize the field**

In `tests/presentation/widgets/test_graph_signals.py`, find the body of `_make_widget`. Locate the line `w._pending_scroll_oid = None`. After it, add:

```python
    w._pending_merge_base = None
```

- [ ] **Step 5: Update `reload_with_extra_tip` to compute merge base**

In `git_gui/presentation/widgets/graph.py`, find the existing method:

```python
    def reload_with_extra_tip(self, oid: str) -> None:
        """Reload graph including the given oid as an extra walker tip, then scroll to it."""
        # If oid is already in the current commit list, just scroll and select
        for row in range(self._model.rowCount()):
            row_oid = self._model.data(self._model.index(row, 0), Qt.UserRole)
            if row_oid == oid:
                self.scroll_to_oid(oid, select=True)
                return
        # Otherwise reload with extra tip and scroll after load
        self._pending_scroll_oid = oid
        self.reload(extra_tips=[oid])
```

Replace the entire method body with:

```python
    def reload_with_extra_tip(self, oid: str) -> None:
        """Reload graph including the given oid as an extra walker tip, then
        scroll to it. For diverged tips, also load down to the merge base with
        HEAD so the lane converges into HEAD's mainline visually."""
        # If oid is already in the current commit list, just scroll and select
        for row in range(self._model.rowCount()):
            row_oid = self._model.data(self._model.index(row, 0), Qt.UserRole)
            if row_oid == oid:
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

- [ ] **Step 6: Run the new test to verify it passes**

Run: `uv run pytest tests/presentation/widgets/test_graph_signals.py::test_reload_with_extra_tip_computes_merge_base_for_diverged_tip -v`

Expected: PASS.

- [ ] **Step 7: Run the existing graph tests to verify no regressions**

Run: `uv run pytest tests/presentation/widgets/test_graph_signals.py -v`

Expected: all tests pass — including `test_reload_with_extra_tip_short_circuits_when_oid_present` (the fast-path early return is preserved).

- [ ] **Step 8: Run the full test suite**

Run: `uv run pytest tests/ 2>&1 | tail -3`

Expected: all tests pass (536: +1 new).

- [ ] **Step 9: Commit**

```bash
git add git_gui/presentation/widgets/graph.py tests/presentation/widgets/test_graph_signals.py
git commit -m "$(cat <<'EOF'
feat(graph): compute merge base in reload_with_extra_tip

Adds MAX_RELOAD_LIMIT constant and a _pending_merge_base field on
GraphWidget. When the clicked oid is not already in the model, look up
the merge base with HEAD and stash it; the field is read by
_on_reload_done in the next commit. Behavior is unchanged for users
until the gate update lands.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds.

---

## Task 5: Gate `_on_reload_done` on the merge base being loaded

**Files:**
- Modify: `git_gui/presentation/widgets/graph.py`
- Test: `tests/presentation/widgets/test_graph_signals.py`

This is the actual behavior change. The existing block at the top of `_on_reload_done` checked only the target oid; now it also requires the merge base to be in `loaded_oids`, and the doubling retry is capped at `MAX_RELOAD_LIMIT`.

- [ ] **Step 1: Write the failing test for retry-until-base-loaded**

Open `tests/presentation/widgets/test_graph_signals.py`. Append at the end:

```python
# ── 6. _on_reload_done gates on merge base ──────────────────────────────


def _make_commit_with_oid(oid):
    """Helper for the gate tests — minimal Commit with just the oid set."""
    return _make_commit(oid)


def test_on_reload_done_retries_when_merge_base_not_loaded(qtbot):
    """If the target is loaded but the merge base is not, and _has_more is
    True and the limit is below the cap, reload is called again with the
    limit doubled."""
    from git_gui.presentation.models.graph_model import GraphModel
    w = _make_widget(qtbot, commits=[_make_commit("HEAD"), _make_commit("DIV")])
    # Reset model so the on_reload_done loop sees the loaded set after this call.
    w._model = GraphModel(
        [_make_commit("HEAD"), _make_commit("DIV")], {},
    )
    w._pending_scroll_oid = "DIV"
    w._pending_merge_base = "BASE"  # NOT in the loaded set
    w._has_more = True
    w._reload_limit = 50
    w._extra_tips = ["DIV"]
    w.reload = MagicMock()

    w._on_reload_done(
        commits=[_make_commit("HEAD"), _make_commit("DIV")],
        branches=[], tags=[], is_dirty=False, head_oid="HEAD",
        repo_state_info=None, merge_head=None,
    )

    # Pending state preserved; reload called again with doubled limit.
    assert w._pending_scroll_oid == "DIV"
    assert w._pending_merge_base == "BASE"
    w.reload.assert_called_once_with(extra_tips=["DIV"], limit=100)


def test_on_reload_done_scrolls_when_target_and_base_both_loaded(qtbot):
    """When both target and merge base are in the loaded set, scroll and
    clear pending state — no further reload."""
    from git_gui.presentation.models.graph_model import GraphModel
    w = _make_widget(qtbot, commits=[
        _make_commit("HEAD"), _make_commit("DIV"), _make_commit("BASE"),
    ])
    w._model = GraphModel([
        _make_commit("HEAD"), _make_commit("DIV"), _make_commit("BASE"),
    ], {})
    w._pending_scroll_oid = "DIV"
    w._pending_merge_base = "BASE"
    w._has_more = True
    w._reload_limit = 50
    w._extra_tips = ["DIV"]
    w.reload = MagicMock()

    w._on_reload_done(
        commits=[
            _make_commit("HEAD"), _make_commit("DIV"), _make_commit("BASE"),
        ],
        branches=[], tags=[], is_dirty=False, head_oid="HEAD",
        repo_state_info=None, merge_head=None,
    )

    assert w._pending_scroll_oid is None
    assert w._pending_merge_base is None
    w.reload.assert_not_called()
    # scroll_to_oid hits _view.setCurrentIndex on the matching row.
    assert w._view.setCurrentIndex.call_count == 1


def test_on_reload_done_gives_up_at_max_reload_limit(qtbot):
    """When _reload_limit is already at MAX_RELOAD_LIMIT and the merge base
    is still not loaded, clear pending state and stop retrying."""
    from git_gui.presentation.models.graph_model import GraphModel
    from git_gui.presentation.widgets.graph import MAX_RELOAD_LIMIT
    w = _make_widget(qtbot, commits=[_make_commit("HEAD"), _make_commit("DIV")])
    w._model = GraphModel(
        [_make_commit("HEAD"), _make_commit("DIV")], {},
    )
    w._pending_scroll_oid = "DIV"
    w._pending_merge_base = "BASE"  # not in the loaded set
    w._has_more = True
    w._reload_limit = MAX_RELOAD_LIMIT  # already at the cap
    w._extra_tips = ["DIV"]
    w.reload = MagicMock()

    w._on_reload_done(
        commits=[_make_commit("HEAD"), _make_commit("DIV")],
        branches=[], tags=[], is_dirty=False, head_oid="HEAD",
        repo_state_info=None, merge_head=None,
    )

    assert w._pending_scroll_oid is None
    assert w._pending_merge_base is None
    w.reload.assert_not_called()


def test_on_reload_done_skips_base_check_when_pending_merge_base_is_none(qtbot):
    """When _pending_merge_base is None (HEAD unborn, branch == HEAD, or
    disjoint histories), only the target gate applies — same as today's
    behavior."""
    from git_gui.presentation.models.graph_model import GraphModel
    w = _make_widget(qtbot, commits=[_make_commit("HEAD"), _make_commit("DIV")])
    w._model = GraphModel(
        [_make_commit("HEAD"), _make_commit("DIV")], {},
    )
    w._pending_scroll_oid = "DIV"
    w._pending_merge_base = None
    w._has_more = True
    w._reload_limit = 50
    w._extra_tips = ["DIV"]
    w.reload = MagicMock()

    w._on_reload_done(
        commits=[_make_commit("HEAD"), _make_commit("DIV")],
        branches=[], tags=[], is_dirty=False, head_oid="HEAD",
        repo_state_info=None, merge_head=None,
    )

    # Target loaded + base check skipped → scroll, no retry.
    assert w._pending_scroll_oid is None
    assert w._pending_merge_base is None
    w.reload.assert_not_called()
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest tests/presentation/widgets/test_graph_signals.py -k "on_reload_done" -v`

Expected: FAILures — primarily because the existing `_on_reload_done` does not check `_pending_merge_base`, so:
- `test_on_reload_done_retries_when_merge_base_not_loaded`: target is loaded → existing code scrolls and clears, no retry → assertion `_pending_scroll_oid == "DIV"` fails.
- `test_on_reload_done_scrolls_when_target_and_base_both_loaded`: passes coincidentally.
- `test_on_reload_done_gives_up_at_max_reload_limit`: passes coincidentally (target loaded → existing code already exits cleanly).
- `test_on_reload_done_skips_base_check_when_pending_merge_base_is_none`: passes coincidentally.

It's enough that at least one test fails for the right reason. Surface the failures.

- [ ] **Step 3: Update `_on_reload_done`**

Open `git_gui/presentation/widgets/graph.py`. Find the existing block in `_on_reload_done`:

```python
        if self._pending_scroll_oid:
            # Check if the target oid was found in loaded commits
            found = any(
                self._model.data(self._model.index(r, 0), Qt.UserRole) == self._pending_scroll_oid
                for r in range(self._model.rowCount())
            )
            if found:
                self.scroll_to_oid(self._pending_scroll_oid, select=True)
                self._pending_scroll_oid = None
            elif self._has_more:
                # Target not found yet — retry with double the limit
                oid = self._pending_scroll_oid
                tips = self._extra_tips
                new_limit = self._reload_limit * 2
                self._pending_scroll_oid = oid
                self._loading = False
                self.reload(extra_tips=tips, limit=new_limit)
            else:
                # No more commits to load — give up
                self._pending_scroll_oid = None
```

Replace it with:

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

The block immediately below (`if self._pending_search:`) stays unchanged.

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `uv run pytest tests/presentation/widgets/test_graph_signals.py -k "on_reload_done" -v`

Expected: 4 passed.

- [ ] **Step 5: Run all `test_graph_signals.py` tests**

Run: `uv run pytest tests/presentation/widgets/test_graph_signals.py -v`

Expected: all tests pass — the existing tests for row selection, `scroll_to_oid`, `set_buses`, etc. still pass.

- [ ] **Step 6: Run the full test suite**

Run: `uv run pytest tests/ 2>&1 | tail -3`

Expected: all tests pass (540: +4 new).

- [ ] **Step 7: Commit**

```bash
git add git_gui/presentation/widgets/graph.py tests/presentation/widgets/test_graph_signals.py
git commit -m "$(cat <<'EOF'
fix(graph): gate reload retry on merge base, not just target oid

When the user clicks a diverged branch, the existing retry stops as soon
as the clicked oid is loaded — but the diverged lane has no convergence
row to draw against if the merge base is not also loaded, leaving the
tip as a floating circle with a stub edge.

Build loaded_oids once per call, require both the target and the merge
base (when known) to be present before scrolling, and cap the doubling
retry at MAX_RELOAD_LIMIT to bound the worst case.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds.

---

## Task 6: Manual verification

**Files:** none modified. No commit.

UI behavior cannot be exercised by the unit suite. This is a smoke test on the running app.

- [ ] **Step 1: Launch the app**

Run: `uv run python main.py`

Expected: app launches without errors.

- [ ] **Step 2: Reproduce the original symptom on the unfixed code (optional)**

If you want to confirm the fix is the cause of the improvement, first check out master before this branch's commits, run the app, click a diverged branch, observe the floating circle, then return to this branch.

- [ ] **Step 3: Verify the fix on this branch**

In the app:
1. Open a repo with at least one branch diverged from HEAD (the GitStack repo itself works — feature branches off `master`).
2. In the sidebar, single-click a branch that is diverged from HEAD (not strictly an ancestor or descendant).

Expected:
- The graph reloads.
- The clicked branch's tip appears as a circle in its own lane.
- A continuous lane line runs from the tip down to the merge base with HEAD.
- At the merge base row, a diagonal edge_in line visibly connects the diverged lane back into HEAD's mainline.

- [ ] **Step 4: Verify the cap on a hypothetical huge divergence**

If you have access to a repo where the diverged branch is thousands of commits behind HEAD (i.e. the merge base is far in the past), click the branch.

Expected: the loader doubles a few times, hits `MAX_RELOAD_LIMIT = 2000`, and stops. The graph shows a partial view; the user can still scroll to load more manually.

- [ ] **Step 5: Verify the unchanged paths**

1. Click a branch whose tip is already loaded (a recent branch). Expected: instant scroll, no flicker.
2. Click a tag (the `tag_clicked` signal also feeds `reload_with_extra_tip`). Expected: same behavior as a branch click.
3. Empty repo (HEAD unborn). Expected: no crashes.

If all five steps pass, the fix is verified end-to-end.

---

## Self-Review Notes

- **Spec coverage:** every "Files Changed" row in the spec maps to a task. Domain port → Task 1. Infrastructure → Task 1. Application query → Task 2. Bus → Task 3. Constant + field → Task 4. `reload_with_extra_tip` → Task 4. `_on_reload_done` → Task 5. Each spec test (infrastructure / query / widget) is implemented in the corresponding task.
- **Type/symbol consistency:** `merge_base` is the method name everywhere. `GetMergeBase` is the query class name. `get_merge_base` is the bus field name. `_pending_merge_base` is the instance field. `MAX_RELOAD_LIMIT = 2000` is the constant. No drift between tasks.
- **No placeholders:** every step has either runnable commands or literal code blocks. No "TODO", no "fill in", no "similar to Task N".
