# MainWindow Session Factory + Tag-Cache Logging — Design

**Date:** 2026-04-17
**Status:** Proposed

## Goal

Remove the one remaining Clean Architecture violation in the presentation layer and replace two silent `except Exception: pass` blocks that mask real tag-cache failures.

The rest of the codebase already respects the dependency rule (presentation → application → domain ← infrastructure). This bundle brings `main_window.py` into line, and tightens error surfacing on two cache paths flagged during the code-health survey.

## Scope

- Inject a `session_factory` callable into `MainWindow` so `main_window.py` no longer imports `git_gui.infrastructure.pygit2_repo`.
- Move the `Pygit2Repository` → `(QueryBus, CommandBus)` wiring into a single helper in `main.py` (the composition root) that both the initial repo open and `_switch_repo` share.
- Replace the two `except Exception: pass` blocks in `_on_delete_tag` and `_delete_tag_local_and_remote` with `logger.warning(...)` calls.

## UX Decisions

| Concern | Decision |
|---|---|
| Where the factory lives | `main.py` as a local function `_open_session(path)`. No new module. |
| Factory signature | `Callable[[str], tuple[QueryBus, CommandBus]]`. |
| Factory injection point | New required constructor argument on `MainWindow`. |
| Worker thread | Unchanged — `_switch_repo` still spawns `threading.Thread` and emits via `_RepoReadySignals`. The factory is called inside the worker. |
| Error handling on factory failure | Unchanged — `except Exception` in the worker already emits `failed`. |
| Logging on cache failures | `logger.warning("Remote tag cache load failed: %s", e)` / `save failed` — message names the operation so debug output is actionable. |
| Logger instance | Reuse the module-level `logger = logging.getLogger(__name__)` that already exists in `main_window.py`. Add it if missing. |

## Approach

`main_window.py` stops knowing how to build a repository session. `main.py` continues as the composition root — it imports the concrete infrastructure class and constructs the buses — but exposes that wiring as a single callable that `MainWindow` receives at construction.

The two tag-cache failure paths change from `pass` to `logger.warning`. Both paths are genuinely recoverable (the worst case is a single missed remote in the "tag has remote?" check), so the handler shape stays identical — only the observability improves.

## Architecture & files touched

**Modified files:**

```
main.py                                # Add _open_session helper, pass to MainWindow
git_gui/presentation/main_window.py    # Drop Pygit2Repository import; accept session_factory;
                                       # replace two `except: pass` with logger.warning
tests/presentation/test_main_window_session_factory.py   # new — regression test
```

**Not touched:** domain, application, infrastructure, all other presentation widgets, dialogs, models, theme, QSS, README.

## `main.py` changes

Introduce a module-level helper and route both call sites through it:

```python
def _open_session(path: str) -> tuple[QueryBus, CommandBus]:
    repo = Pygit2Repository(path)
    return QueryBus.from_reader(repo), CommandBus.from_writer(repo)
```

The existing three-line block at `main.py:81-83`:

```python
repo = Pygit2Repository(repo_path)
queries = QueryBus.from_reader(repo)
commands = CommandBus.from_writer(repo)
```

becomes:

```python
queries, commands = _open_session(repo_path)
```

`MainWindow` construction at `main.py:85` gains one extra argument:

```python
window = MainWindow(queries, commands, repo_store, remote_tag_cache, repo_path,
                    session_factory=_open_session)
```

## `main_window.py` changes

**Drop the import** at `main_window.py:12`:

```python
from git_gui.infrastructure.pygit2_repo import Pygit2Repository   # REMOVE
```

**Accept the factory** in `MainWindow.__init__`. The new keyword-only parameter keeps the call site readable and avoids positional-arg creep:

```python
def __init__(
    self,
    queries: QueryBus,
    commands: CommandBus,
    repo_store: JsonRepoStore,
    remote_tag_cache: JsonRemoteTagCache,
    repo_path: str,
    *,
    session_factory: Callable[[str], tuple[QueryBus, CommandBus]],
) -> None:
    ...
    self._session_factory = session_factory
```

Add the `Callable` import at the top of the file from `typing`.

**Use the factory** in `_switch_repo` (currently `main_window.py:713-728`). Replace the worker body:

```python
def _worker():
    try:
        repo = Pygit2Repository(path)
        queries = QueryBus.from_reader(repo)
        commands = CommandBus.from_writer(repo)
        signals.ready.emit(path, queries, commands)
    except Exception as e:
        signals.failed.emit(path, str(e))
```

with:

```python
def _worker():
    try:
        queries, commands = self._session_factory(path)
        signals.ready.emit(path, queries, commands)
    except Exception as e:
        signals.failed.emit(path, str(e))
```

**Verify the logger exists.** If `main_window.py` does not already have `logger = logging.getLogger(__name__)` near the top, add it alongside the `import logging` statement.

**Replace the two silent excepts.**

At `main_window.py:596-603` (inside `_on_delete_tag`):

```python
if self._remote_tag_cache and self._repo_path:
    try:
        cache_data = self._remote_tag_cache.load(self._repo_path)
        for remote, names in cache_data.items():
            if name in names:
                remotes_with_tag.append(remote)
    except Exception as e:
        logger.warning("Remote tag cache load failed for %s: %s", self._repo_path, e)
```

At `main_window.py:659-666` (inside `_delete_tag_local_and_remote._fn`):

```python
if self._remote_tag_cache and self._repo_path:
    try:
        data = self._remote_tag_cache.load(self._repo_path)
        if r in data and name in data[r]:
            data[r] = [t for t in data[r] if t != name]
            self._remote_tag_cache.save(self._repo_path, data)
    except Exception as e:
        logger.warning(
            "Remote tag cache update failed for %s (remote=%s, tag=%s): %s",
            self._repo_path, r, name, e,
        )
```

Messages include the repo path and, where applicable, the remote/tag so the log line is actionable without further context.

## Testing

**`tests/presentation/test_main_window_session_factory.py`** (pytest-qt):

- `test_main_window_calls_session_factory_on_switch_repo` — construct `MainWindow` with a stub factory that records calls; invoke `_switch_repo("some/path")`; wait on `_RepoReadySignals.ready` via `qtbot.waitSignal`; assert the stub was called exactly once with `"some/path"` and the emitted `queries`/`commands` are the stub's return values.
- `test_main_window_factory_failure_emits_failed_signal` — factory raises; assert `_RepoReadySignals.failed` is emitted with the exception message.
- `test_main_window_no_pygit2_import` — read the source of `git_gui/presentation/main_window.py` and assert `"git_gui.infrastructure"` does not appear anywhere in it. This is a regression guard that catches any form of the import (`from`, bare `import`, alias).

Existing tests are unchanged except any that construct `MainWindow` directly — those gain the keyword argument `session_factory=lambda _: (MagicMock(), MagicMock())`. A grep of the test tree should identify them.

**No test for the log messages themselves** — the intent is that `pass` becomes `warning`; log-message text is not part of the contract.

## Out of scope

- Splitting `main_window.py` into multiple presenter classes (sub-project C).
- Splitting `infrastructure/pygit2_repo.py` (sub-project B).
- Introducing a `git_gui/composition.py` module — premature until a second caller needs the factory.
- Replacing `threading.Thread` with `QThread`.
- Auditing other `except Exception: pass` sites elsewhere in the codebase (none flagged by the survey).
- Changing `MainWindow`'s other constructor arguments.
