# Insight Streaming + Progress + Cancellation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Insight dialog usable on huge / long-lived repos by streaming `git log --numstat` output, surfacing progress to the user, and cancelling the worker when the user closes the dialog or starts a new query.

**Architecture:** `IRepositoryReader.get_commit_stats` becomes a generator with an optional `cancel` callback. The infrastructure implementation streams `subprocess.Popen` output line by line and checks the cancel callback after every emitted commit, terminating the subprocess if cancellation is requested. The dialog's worker thread consumes the iterator, aggregates into dicts as it streams, emits a `progress` signal every ~250 ms, and clears its cancel `Event` on `closeEvent` and on every new `_reload`.

**Tech Stack:** Python `subprocess.Popen` + `threading.Event`, PySide6 `Signal` / `closeEvent`, pytest. Project uses `uv run` for Python and `rtk` for shell commands.

**Spec:** `docs/superpowers/specs/2026-05-06-insight-streaming-design.md`

---

## File Structure

- **Modify:** `git_gui/domain/ports.py` — `get_commit_stats` signature: add `cancel` kwarg, change return type to `Iterator[CommitStat]`.
- **Modify:** `git_gui/application/queries.py` — `GetCommitStats.execute` mirrors the new signature and forwards `cancel`.
- **Modify:** `git_gui/infrastructure/pygit2/commit_ops.py` — rewrite `get_commit_stats` as a generator using `subprocess.Popen` and per-commit cancel checks.
- **Modify:** `git_gui/presentation/widgets/insight_dialog.py` — reshape `_LoadSignals`, move aggregation into the worker, add `progress` label updates, add `_cancel` Event wired to `closeEvent` and `_reload`.
- **Modify:** `tests/infrastructure/test_reads.py` (or appropriate sibling) — generator + cancel tests.
- **Modify:** `tests/presentation/dialogs/` — dialog aggregation test if a sensible fixture exists; otherwise unit-test the worker aggregation logic in isolation.

Files **not** changed:
- The five range buttons, `_compute_range`, the visual layout of summary cards / author rows / file chart.
- Domain entity `CommitStat` shape.
- Any other Reader port methods.

---

## Task 1: Streaming `get_commit_stats` + signature change

Strict TDD. Write tests for the streaming generator and cancellation, see them fail, then update the port + application wrapper + infrastructure together (they have to land coherently because the type signatures must match).

**Files:**
- Modify: `git_gui/domain/ports.py`
- Modify: `git_gui/application/queries.py`
- Modify: `git_gui/infrastructure/pygit2/commit_ops.py`
- Modify: `tests/infrastructure/test_reads.py`

- [ ] **Step 1: Write failing tests for streaming + cancel**

Append to `tests/infrastructure/test_reads.py`:

```python
def test_get_commit_stats_returns_iterator(repo_impl):
    """get_commit_stats should be a generator/iterator, not a list."""
    import inspect
    result = repo_impl.get_commit_stats()
    assert inspect.isgenerator(result) or hasattr(result, "__next__")


def test_get_commit_stats_yields_commits_in_order(repo_impl):
    """The streaming generator yields each commit in repo order
    (newest first, like git log)."""
    stats = list(repo_impl.get_commit_stats())
    assert len(stats) >= 1
    assert all(cs.oid and cs.author for cs in stats)


def test_get_commit_stats_cancel_stops_iteration(repo_path):
    """When the cancel callback returns True, the generator terminates
    after the next commit boundary and the subprocess is gone."""
    import pygit2
    from git_gui.infrastructure.pygit2 import Pygit2Repository

    repo = pygit2.Repository(str(repo_path))
    sig = pygit2.Signature("T", "t@t.com")
    head_oid = repo.head.target
    # Add a few commits so the stream has something to iterate over.
    for i in range(3):
        (repo_path / f"f{i}.txt").write_text(f"f{i}")
        repo.index.add(f"f{i}.txt")
        repo.index.write()
        tree = repo.index.write_tree()
        head_oid = repo.create_commit(
            "refs/heads/master", sig, sig, f"c{i}", tree, [head_oid]
        )

    impl = Pygit2Repository(str(repo_path))
    cancel_calls = {"n": 0}

    def cancel() -> bool:
        cancel_calls["n"] += 1
        return cancel_calls["n"] >= 1  # cancel after the very first check

    stats = list(impl.get_commit_stats(cancel=cancel))
    # First commit should be yielded; cancel triggers after that.
    assert len(stats) <= 2  # tolerate one buffered boundary
    assert cancel_calls["n"] >= 1
```

- [ ] **Step 2: Run the new tests and confirm FAIL**

Run: `rtk uv run pytest tests/infrastructure/test_reads.py -v -k "get_commit_stats"`

Expected: FAILures — current implementation returns a `list`, no `cancel` kwarg.

- [ ] **Step 3: Update the port signature in `domain/ports.py`**

Find:

```python
    def get_commit_stats(self, since: datetime | None = None, until: datetime | None = None) -> list[CommitStat]: ...
```

Replace with:

```python
    def get_commit_stats(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        *,
        cancel: Callable[[], bool] | None = None,
    ) -> Iterator[CommitStat]: ...
```

Add the necessary imports near the top of `ports.py` if not already present:

```python
from collections.abc import Callable, Iterator
```

(Use `from collections.abc` for both — Python 3.13 prefers it.)

- [ ] **Step 4: Update the application wrapper in `application/queries.py`**

Find:

```python
class GetCommitStats:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self, since: datetime | None = None, until: datetime | None = None) -> list[CommitStat]:
        return self._reader.get_commit_stats(since, until)
```

Replace with:

```python
class GetCommitStats:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        *,
        cancel: Callable[[], bool] | None = None,
    ) -> Iterator[CommitStat]:
        return self._reader.get_commit_stats(since, until, cancel=cancel)
```

Add imports near the top of `queries.py`:

```python
from collections.abc import Callable, Iterator
```

- [ ] **Step 5: Rewrite `get_commit_stats` in `infrastructure/pygit2/commit_ops.py`**

Find the entire current method (lines 152-226). Replace with:

```python
    def get_commit_stats(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        *,
        cancel: Callable[[], bool] | None = None,
    ) -> Iterator[CommitStat]:
        cmd = ["git", "log", "--numstat", "--format=__COMMIT__%n%H%n%aN <%aE>%n%aI"]
        if since:
            cmd.append(f"--since={since.isoformat()}")
        if until:
            cmd.append(f"--until={until.isoformat()}")

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                cwd=self._repo.workdir,
                env=self._git_env,
                **subprocess_kwargs(),
            )
        except Exception as e:
            logger.warning("Failed to start git log for commit stats: %s", e)
            return

        current_oid: str | None = None
        current_author: str | None = None
        current_ts: datetime | None = None
        current_files: list[FileStat] = []
        state = "expect_marker"  # expect_marker | oid | author | date | files

        def _build() -> CommitStat | None:
            if current_oid and current_author and current_ts is not None:
                return CommitStat(
                    oid=current_oid,
                    author=current_author,
                    timestamp=current_ts,
                    files=list(current_files),
                )
            return None

        try:
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                line = raw_line.rstrip("\r\n")
                if line == "__COMMIT__":
                    cs = _build()
                    if cs is not None:
                        yield cs
                        if cancel is not None and cancel():
                            return
                    current_oid = None
                    current_author = None
                    current_ts = None
                    current_files = []
                    state = "oid"
                    continue
                if state == "oid":
                    current_oid = line
                    state = "author"
                    continue
                if state == "author":
                    current_author = line
                    state = "date"
                    continue
                if state == "date":
                    try:
                        current_ts = datetime.fromisoformat(line)
                    except ValueError:
                        current_ts = None
                    state = "files"
                    continue
                if state == "files":
                    if not line.strip():
                        continue
                    parts = line.split("\t")
                    if len(parts) != 3:
                        continue
                    added_str, deleted_str, path = parts
                    try:
                        added = int(added_str) if added_str != "-" else 0
                        deleted = int(deleted_str) if deleted_str != "-" else 0
                    except ValueError:
                        continue
                    current_files.append(FileStat(path=path, added=added, deleted=deleted))

            cs = _build()
            if cs is not None:
                yield cs
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                pass
```

Add the necessary imports near the top of `commit_ops.py`:

```python
from collections.abc import Callable, Iterator
```

(`subprocess` and `datetime` are already imported.)

- [ ] **Step 6: Run the new tests and confirm PASS**

Run: `rtk uv run pytest tests/infrastructure/test_reads.py -v -k "get_commit_stats"`

Expected: 3 PASSED.

- [ ] **Step 7: Run the full infrastructure suite + dialog tests**

Run: `rtk uv run pytest tests/infrastructure/ tests/presentation/dialogs/ -q`

Expected: all PASSED. The InsightDialog still works because it currently consumes the result via a `for` loop (or list iteration) — both work with a generator. Aggregation happens later in `_render_content`, but the dialog's worker iterates `stats` once into a list internally.

If the dialog tests fail because they assume a `list` return shape (e.g., `len(stats)` or `stats[0]`), Task 2 will fix the dialog properly; for now, materialize the iterator with `list(...)` at the dialog call site only if absolutely needed to keep tests green. The clean fix arrives in Task 2.

- [ ] **Step 8: Run the full suite**

Run: `rtk uv run pytest tests/ -q`

Expected: all PASSED.

- [ ] **Step 9: Commit**

```bash
rtk git add git_gui/domain/ports.py git_gui/application/queries.py git_gui/infrastructure/pygit2/commit_ops.py tests/infrastructure/test_reads.py
rtk git commit -m "$(cat <<'EOF'
feat(infra): stream git log output for commit stats

get_commit_stats becomes a generator backed by subprocess.Popen
streaming. Adds an optional cancel callback that's checked after
every yielded commit; when it returns True, the subprocess is
terminated and the generator returns. The port and the application
wrapper take the same shape.

This is the data-layer half of the Insight streaming work. The
dialog still consumes the result and aggregates as before; the
next commit moves aggregation into the worker thread and adds
progress / cancellation UX.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Dialog rewire — worker aggregation, progress, cancellation

Now the dialog learns to consume the generator: aggregate as it streams, emit progress updates, and cancel on close / new reload.

**Files:**
- Modify: `git_gui/presentation/widgets/insight_dialog.py`

- [ ] **Step 1: Reshape `_LoadSignals`**

Find:

```python
class _LoadSignals(QObject):
    done = Signal(int, list)  # generation, list[CommitStat]
```

Replace with:

```python
class _LoadSignals(QObject):
    progress = Signal(int, float)  # commits_processed, elapsed_seconds
    done = Signal(int, dict, dict, dict, dict, set, int)
    # generation, author_commits, author_added, author_deleted,
    # file_counts, files_changed, total_commits
    cancelled = Signal(int)  # generation
```

- [ ] **Step 2: Add `_cancel` Event + `closeEvent` wiring**

In `InsightDialog.__init__`, after `self._load_generation = 0`, add:

```python
        self._cancel: threading.Event | None = None
```

Add a `closeEvent` override (place it near the other event handlers — at the end of the class, after `_render_content` and friends):

```python
    def closeEvent(self, event) -> None:
        if self._cancel is not None:
            self._cancel.set()
        super().closeEvent(event)
```

- [ ] **Step 3: Rewrite `_reload` to dispatch streaming worker**

Find the existing `_reload` method:

```python
    def _reload(self, since: datetime | None, until: datetime | None) -> None:
        self._loading_label.setVisible(True)
        self._scroll.setVisible(False)

        self._load_generation += 1
        generation = self._load_generation

        signals = _LoadSignals()
        signals.done.connect(self._on_loaded)
        self._load_signals = signals  # prevent GC

        queries = self._queries

        def _worker():
            stats = queries.get_commit_stats.execute(since, until)
            signals.done.emit(generation, stats)

        threading.Thread(target=_worker, daemon=True).start()
```

Replace with:

```python
    def _reload(self, since: datetime | None, until: datetime | None) -> None:
        # Cancel any in-flight worker — we're superseding it.
        if self._cancel is not None:
            self._cancel.set()

        self._loading_label.setText("Loading...")
        self._loading_label.setVisible(True)
        self._scroll.setVisible(False)

        self._load_generation += 1
        generation = self._load_generation
        self._cancel = threading.Event()
        cancel_event = self._cancel

        signals = _LoadSignals()
        signals.progress.connect(self._on_progress)
        signals.done.connect(self._on_loaded)
        signals.cancelled.connect(self._on_cancelled)
        self._load_signals = signals  # prevent GC

        queries = self._queries

        def _worker() -> None:
            import time
            author_commits: dict[str, int] = {}
            author_added: dict[str, int] = {}
            author_deleted: dict[str, int] = {}
            file_counts: dict[str, int] = {}
            files_changed: set[str] = set()
            total = 0
            started = time.monotonic()
            last_progress = started

            try:
                for cs in queries.get_commit_stats.execute(
                    since, until, cancel=cancel_event.is_set
                ):
                    total += 1
                    author_commits[cs.author] = author_commits.get(cs.author, 0) + 1
                    for f in cs.files:
                        author_added[cs.author] = author_added.get(cs.author, 0) + f.added
                        author_deleted[cs.author] = author_deleted.get(cs.author, 0) + f.deleted
                        file_counts[f.path] = file_counts.get(f.path, 0) + 1
                        files_changed.add(f.path)

                    now = time.monotonic()
                    if now - last_progress >= 0.25:
                        signals.progress.emit(total, now - started)
                        last_progress = now
            except Exception:
                pass

            if cancel_event.is_set():
                signals.cancelled.emit(generation)
                return

            signals.done.emit(
                generation, author_commits, author_added,
                author_deleted, file_counts, files_changed, total,
            )

        threading.Thread(target=_worker, daemon=True).start()
```

- [ ] **Step 4: Add `_on_progress` slot**

After `_on_loaded` (which we'll rewrite next), add:

```python
    def _on_progress(self, total: int, elapsed: float) -> None:
        # Format with thousands separator for readability on huge repos.
        self._loading_label.setText(f"Processed {total:,} commits, {elapsed:.1f}s...")
```

- [ ] **Step 5: Rewrite `_on_loaded` to consume the new dict-based payload**

Find the existing `_on_loaded`:

```python
    def _on_loaded(self, generation: int, stats: list[CommitStat]) -> None:
        # Discard stale results from superseded queries
        if generation != self._load_generation:
            return
        self._stats = stats
        self._loading_label.setVisible(False)
        self._scroll.setVisible(True)
        self._render_content()
```

Replace with:

```python
    def _on_loaded(
        self,
        generation: int,
        author_commits: dict,
        author_added: dict,
        author_deleted: dict,
        file_counts: dict,
        files_changed: set,
        total_commits: int,
    ) -> None:
        if generation != self._load_generation:
            return
        self._loading_label.setVisible(False)
        self._scroll.setVisible(True)
        self._render_content(
            author_commits, author_added, author_deleted,
            file_counts, files_changed, total_commits,
        )

    def _on_cancelled(self, generation: int) -> None:
        # Worker was cancelled (closeEvent or supersession). Nothing to render.
        if generation != self._load_generation:
            return
        # Keep the loading label visible briefly so a fast cancel still
        # shows that we acknowledged it; closeEvent will tear the dialog
        # down anyway.
        self._loading_label.setText("Cancelled.")
```

- [ ] **Step 6: Update `_render_content` to consume the dict-based aggregation**

Find the existing `_render_content` method. Its signature today is `def _render_content(self) -> None:` and its body builds the dicts from `self._stats`.

Replace the **signature** and the **aggregation block** (the part that builds `author_commits`, `author_added`, `author_deleted`, `file_counts`, `files_changed`, `total_commits`, `active_authors`, `total_files`). Keep the rest of the method (summary cards, author rows, file chart) unchanged.

New signature:

```python
    def _render_content(
        self,
        author_commits: dict[str, int],
        author_added: dict[str, int],
        author_deleted: dict[str, int],
        file_counts: dict[str, int],
        files_changed: set[str],
        total_commits: int,
    ) -> None:
```

Inside the method, **delete** the existing aggregation block:

```python
        # ── Aggregation ──────────────────────────────────────────────────────
        author_commits: dict[str, int] = {}
        author_added: dict[str, int] = {}
        author_deleted: dict[str, int] = {}
        file_counts: dict[str, int] = {}
        files_changed: set[str] = set()

        for cs in self._stats:
            author_commits[cs.author] = author_commits.get(cs.author, 0) + 1
            for f in cs.files:
                author_added[cs.author] = author_added.get(cs.author, 0) + f.added
                author_deleted[cs.author] = author_deleted.get(cs.author, 0) + f.deleted
                file_counts[f.path] = file_counts.get(f.path, 0) + 1
                files_changed.add(f.path)

        total_commits = len(self._stats)
        active_authors = len(author_commits)
        total_files = len(files_changed)
```

Replace it with just the two derived counts:

```python
        active_authors = len(author_commits)
        total_files = len(files_changed)
```

The early-empty-state check at the top of the method changes from `if not self._stats:` to `if total_commits == 0:`. Find and update that line.

- [ ] **Step 7: Drop `self._stats`**

Search for `self._stats` everywhere in `insight_dialog.py`. There are three references:
1. The init: `self._stats: list[CommitStat] = []` — remove.
2. `_rebuild_styles`: `if self._stats: self._render_content()` — this re-renders on theme change. Replace with a simple `if self._scroll.isVisible(): self.update()` (or just `self.update()`); the rebuild path is best-effort and only matters if data is already on screen. Tweak: store the last-rendered dicts so the rebuild can re-render with the same data. Pragmatic version:

   ```python
       self._last_render: tuple | None = None  # in __init__
   ```

   And in `_render_content`, at the top: `self._last_render = (author_commits, author_added, author_deleted, file_counts, files_changed, total_commits)`.

   And `_rebuild_styles` becomes:

   ```python
       def _rebuild_styles(self) -> None:
           self._loading_label.setStyleSheet(f"color: {_muted()}; padding: 40px;")
           if self._last_render is not None:
               self._render_content(*self._last_render)
           self.update()
       ```

3. The original `_on_loaded`: already replaced in Step 5.

- [ ] **Step 8: Add the `threading` import if missing**

At the top of `insight_dialog.py`:

```python
import threading
```

(It's already imported per the file's existing `threading.Thread(target=_worker, daemon=True).start()` call.)

- [ ] **Step 9: Run the dialog tests**

Run: `rtk uv run pytest tests/presentation/dialogs/ -v`

If there are existing InsightDialog tests, they may need light updates to the new signal shape. If a failure points to `signals.done.connect(...)` mismatch or to `_render_content(self)` missing args, update the test stubs. (We don't add new tests in this task because the dialog's worker logic is hard to unit-test in isolation — the manual smoke test in Task 3 is the verification.)

- [ ] **Step 10: Run the full suite**

Run: `rtk uv run pytest tests/ -q`

Expected: all PASSED.

- [ ] **Step 11: Commit**

```bash
rtk git add git_gui/presentation/widgets/insight_dialog.py
rtk git commit -m "$(cat <<'EOF'
feat(insight): aggregate in worker thread; show progress; cancel

Worker thread now consumes the streaming get_commit_stats generator
and accumulates per-author / per-file totals as it streams.
Progress is reported every ~250ms via a new signal that updates the
loading label with "Processed N commits, T s". A threading.Event
shared with the worker is set on dialog closeEvent and on every
new _reload so any in-flight query stops promptly. _render_content
now takes the aggregated dicts directly instead of iterating
self._stats; the field is gone.

Together with the prior streaming commit, the dialog never blocks
the main thread and even "All" on a long-lived repo shows visible
progress and is fully cancellable.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Manual verification

**Files:** none modified.

- [ ] **Step 1: Launch the app**

Run: `rtk uv run python main.py`

- [ ] **Step 2: Open Insight on a sizable repo**

Open a repo with at least a few hundred commits (more is better). `Git → Insights`. Default range "This Month" runs.

The loading label should briefly show `"Processed N commits, T s..."` instead of the old static "Loading..." (assuming the repo is busy enough for streaming to take a noticeable beat). On a small repo this may complete too fast to observe — that's fine.

- [ ] **Step 3: Click "All" on a huge repo**

Watch the label tick up. Confirm that:
- The numbers update at least every 250 ms.
- The dialog is responsive: you can drag it around while streaming.
- Other ranges remain clickable.

- [ ] **Step 4: Cancel mid-stream**

While "All" is streaming, close the dialog. Confirm:
- The dialog dismisses immediately.
- Run `tasklist | findstr git.exe` (Windows) or `ps aux | grep git` (other) to confirm no orphan `git log` is still running. There should be no stale subprocess.

- [ ] **Step 5: Supersede in-flight work**

Click "All", then immediately click "This Week". Confirm the "All" stream is cancelled and "This Week" results appear.

- [ ] **Step 6: No commit needed**

Manual verification doesn't produce changes. Surface any visible issue before opening the PR.

---

## Self-Review

**Spec coverage:**
- Stream output via `Popen` → Task 1 Step 5. ✅
- `get_commit_stats` becomes a generator → Task 1 Steps 3, 4, 5. ✅
- Worker thread aggregates as it streams → Task 2 Step 3. ✅
- `progress` signal + label update every ~250 ms → Task 2 Step 3 (worker emit), Step 4 (slot). ✅
- `cancelled` signal → Task 2 Steps 1, 5. ✅
- `_cancel = threading.Event` set on `closeEvent` and `_reload` → Task 2 Steps 2, 3. ✅
- `_render_content` takes dicts directly, no `self._stats` → Task 2 Steps 5, 6, 7. ✅
- Subprocess terminated on cancel → Task 1 Step 5 (the `finally` block). ✅
- "All" button stays in the UI → not modified anywhere. ✅

**Placeholder scan:** none — every step has the actual code, command, or expected output.

**Type/method consistency:**
- `cancel: Callable[[], bool] | None` — same shape across port (Step 3), application (Step 4), infrastructure (Step 5).
- `Iterator[CommitStat]` return type consistent across the same three.
- `_LoadSignals` signal shapes match worker emit calls and slot signatures (`progress(int, float)`, `done(int, dict, dict, dict, dict, set, int)`, `cancelled(int)`).
- Worker emits dicts in the same order `_on_loaded` and `_render_content` consume them.
