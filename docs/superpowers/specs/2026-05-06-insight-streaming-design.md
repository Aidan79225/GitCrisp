# Insight: streaming, progress, cancellation

## Context

The Insight dialog runs `subprocess.run(["git", "log", "--numstat",
"--format=..."])` in a worker thread, captures the entire stdout
into one string, parses it into `list[CommitStat]`, and finally
aggregates on the main thread inside `_render_content`. On a
long-lived repo this can spend many seconds — sometimes minutes —
inside `subprocess.run` before any UI feedback is possible. From
the user's perspective the dialog is "stuck on Loading and never
produces results" because there is no progress signal and no way to
cancel.

The "All" button is unbounded and the most affected, but even "This
Year" can be slow on busy repos. The user wants to keep the "All"
button as-is.

## Fix

Three coordinated changes:

1. **Stream the subprocess output.** Replace `subprocess.run` with
   `subprocess.Popen(..., stdout=PIPE, text=True, bufsize=1)` and
   read `proc.stdout.readline()` line by line. `get_commit_stats`
   becomes a generator (`Iterator[CommitStat]`).
2. **Aggregate in the worker thread.** Pull from the generator and
   accumulate into the four dicts and the `files_changed` set
   (currently built in `_render_content`). Main thread just renders
   the finished aggregation; no block at the end.
3. **Progress + cancellation.** A new `progress` signal updates the
   loading label every ~250 ms with `"Processed N commits, T s"`. A
   `threading.Event` cancel flag, set on dialog `closeEvent` and on
   every new `_reload`, halts the worker and terminates the
   subprocess.

Behavior: the dialog never blocks the main thread, the user sees
visible progress, and closing the dialog actually stops the work.
"All" remains in the UI; it is now slow-but-tolerable instead of
stuck-and-uncancellable.

## Scope

- **Modify:** `git_gui/infrastructure/pygit2/commit_ops.py` —
  `get_commit_stats` becomes a generator with an optional cancel
  callback.
- **Modify:** `git_gui/presentation/widgets/insight_dialog.py` —
  reshape `_LoadSignals`, move aggregation into the worker, add
  `progress` label updates, add `_cancel` Event wired to
  `closeEvent` and `_reload`.
- **Modify:** tests under `tests/infrastructure/` and possibly
  `tests/presentation/dialogs/` (streaming + cancellation +
  aggregation correctness).

## API change: `IRepositoryReader.get_commit_stats`

Today:
```python
def get_commit_stats(self, since: datetime | None = None,
                     until: datetime | None = None) -> list[CommitStat]: ...
```

After:
```python
def get_commit_stats(
    self,
    since: datetime | None = None,
    until: datetime | None = None,
    *,
    cancel: Callable[[], bool] | None = None,
) -> Iterator[CommitStat]: ...
```

The `cancel` callback (if given) is invoked between commits; when
it returns True the generator terminates the subprocess and stops
yielding. The port and the application-layer wrapper update
together. Existing call sites (only the InsightDialog today) are
updated to consume as an iterator.

## Implementation: streaming parser

Inside `get_commit_stats`:

```python
proc = subprocess.Popen(cmd, stdout=PIPE, text=True, bufsize=1, ...)
state = "expect_marker"
current_oid = current_author = current_ts = None
current_files: list[FileStat] = []

def _flush() -> CommitStat | None:
    if current_oid and current_author and current_ts is not None:
        return CommitStat(
            oid=current_oid, author=current_author,
            timestamp=current_ts, files=list(current_files),
        )
    return None

try:
    while True:
        line = proc.stdout.readline()
        if not line:
            break
        line = line.rstrip("\r\n")
        # ... existing state-machine logic, but `flush()` yields ...
        if line == "__COMMIT__":
            cs = _flush()
            if cs:
                yield cs
                if cancel and cancel():
                    proc.terminate()
                    return
            # reset state for next commit
            ...
        # ... rest of the cases mirror current parser ...
    # Final flush after EOF
    cs = _flush()
    if cs:
        yield cs
finally:
    proc.terminate()
    proc.wait(timeout=2)
```

The cancel check happens after every full commit boundary so we
emit consistent rows but respond to cancel within one commit's
worth of work.

## Implementation: dialog worker + progress

`_LoadSignals` reshape:
```python
class _LoadSignals(QObject):
    progress = Signal(int, float)  # commits_processed, elapsed_seconds
    done = Signal(int, dict, dict, dict, dict, set, int)
    # generation, author_commits, author_added, author_deleted,
    # file_counts, files_changed, total_commits
    cancelled = Signal(int)  # generation
```

Worker thread:
```python
def _worker():
    cancel_event = self._cancel  # captured by reference
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
    except Exception as e:
        logger.warning("Insight worker failed: %s", e)

    if cancel_event.is_set():
        signals.cancelled.emit(generation)
        return

    signals.done.emit(
        generation, author_commits, author_added, author_deleted,
        file_counts, files_changed, total,
    )
```

Dialog:
- `_reload` sets `self._cancel` on any previous event (if it
  exists), creates a fresh one, dispatches the worker.
- `_on_progress` updates the loading label.
- `_on_done` renders content from the received dicts.
- `_on_cancelled` does nothing visible — the dialog has either
  moved on (new generation in flight) or has been closed.
- `closeEvent` sets `self._cancel` so any in-flight worker stops
  promptly.

`_render_content` no longer aggregates from `self._stats`; it
renders from the dicts passed via `done`. The `self._stats`
attribute can be removed.

## What stays the same

- The five range buttons including "All".
- `_compute_range` behavior.
- The visual layout of the dialog: summary cards, author rows, file
  chart.
- Domain entity `CommitStat` shape.

## Verification

**Automated:**
```
uv run pytest tests/infrastructure/ -v
uv run pytest tests/presentation/dialogs/ -v
uv run pytest tests/ -q
```

New tests (minimum):
- Streaming generator yields rows in repo order from a small fake
  repo.
- A `cancel=lambda: True` makes the generator return after the
  first yielded commit and terminates the subprocess.
- Aggregation worker test (without Qt): given a fixed sequence of
  CommitStat values, the produced dicts match the expected totals.

**Manual:**
1. Open Insight on a repo with at least a few hundred commits.
   Click "All". The label updates with a counter ("Processed N
   commits, T s") within a second or two; final summary renders
   when streaming completes.
2. Click "All" on a huge repo. Progress visible. Close the dialog
   mid-stream. The dialog dismisses immediately and the git log
   subprocess is terminated (no zombie process).
3. Click "This Year" while "All" is still streaming. The "All"
   work is cancelled; the new query streams.
