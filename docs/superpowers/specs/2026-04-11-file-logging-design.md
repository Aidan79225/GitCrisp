# File Logging + Warning Instrumentation — Design

**Status:** Draft
**Date:** 2026-04-11

## Background

`git_gui/infrastructure/pygit2_repo.py` currently has 12 bare `except Exception:` traps (grep hit lines 187, 313, 337, 346, 359, 378, 440, 456, 976, 994, 1012, 1038). Each one silently swallows the failure and returns a fallback value — usually `None`, an empty list, or an empty dict. The graceful-degradation behavior is correct: we do not want one malformed file in a repo to break the whole diff view. But the silent-failure mode is a diagnostic black hole. When a user reports "the diff was empty", there is no way to tell which code path failed or why.

At the same time, GitStack has no general logging mechanism. `stderr` output is often invisible for desktop GUI apps (Windows double-click, PyInstaller `--windowed` builds, launch from a shortcut), so dropping messages to `stderr` is not a reliable diagnostic channel.

## Goals

- Capture WARNING-level diagnostics from bare-except sites in a persistent file the user (or maintainer) can read after the fact.
- Keep the change minimal: no new dependencies, no config file, no in-app log viewer, no module-level log-level tuning.
- Leave the existing `LogPanel` widget alone. It is audience-facing operation feedback, not a diagnostic channel.

## Non-goals

- In-app log viewer or menu item to open the log file.
- Multiple handlers (stderr, syslog, email, JSON). The file handler is the only sink.
- DEBUG-level logging. WARNING is the floor.
- Integration with Qt's `qInstallMessageHandler` for Qt-internal messages.
- Per-module log-level configuration.
- Log level switches exposed in the UI or env vars. A hard-coded WARNING level is enough for v1.

## Architecture

### New module: `git_gui/logging_setup.py`

A single function, `setup_logging()`, configures the root logger exactly once. It is called from `main.py` before the `QApplication` is created.

```python
# git_gui/logging_setup.py
from __future__ import annotations
import logging
import logging.handlers
from pathlib import Path

_LOG_DIR = Path.home() / ".gitcrisp" / "logs"
_LOG_FILE = _LOG_DIR / "gitcrisp.log"
_MAX_BYTES = 1_000_000  # 1 MB per file
_BACKUP_COUNT = 3       # keep gitcrisp.log.1 .. .3


def setup_logging() -> None:
    """Configure the root logger with a single rotating file handler.

    Idempotent — calling it twice does not install duplicate handlers.
    """
    root = logging.getLogger()
    # Already configured (e.g. by a prior call in tests) → skip
    if any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        return

    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        _LOG_FILE,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    ))
    root.setLevel(logging.WARNING)
    root.addHandler(handler)
```

**Idempotence** is important so that test setup / teardown can call it repeatedly without leaking file handles.

### Integration point: `main.py`

Call `setup_logging()` in `main()` before `QApplication(sys.argv)`. This guarantees all Qt-created objects and any subsequent calls to `logging.getLogger(__name__)` benefit from the handler.

### Instrumented sites in `pygit2_repo.py`

Each of the 12 bare-except sites gets converted from:

```python
except Exception:
    pass
# or
except Exception:
    return <fallback>
```

to:

```python
except Exception as e:
    logger.warning("Failed to <describe operation> for %r: %s", <relevant arg>, e)
    <existing fallback>
```

A single `logger = logging.getLogger(__name__)` is added at the top of `pygit2_repo.py`.

Each log line includes:
- A short human-readable description of the failed operation ("Failed to compute staged diff", "Failed to list submodules", etc.).
- The most relevant argument (usually the path or the oid), formatted with `%r` so strings are quoted and easy to scan.
- The exception message via `%s`. We use lazy `%`-style formatting (not f-strings) so the logger can skip formatting when the message is below threshold.

No exception traceback by default — `logger.warning` without `exc_info=True` keeps the log short. If detailed tracebacks are ever needed, they can be opted into per-site later.

### Log file location

`~/.gitcrisp/logs/gitcrisp.log`

- Cross-platform: `Path.home()` works on Windows, macOS, and Linux.
- Matches the pattern used by other GitStack state (`.gitcrisp/` is already a reasonable place for app data if any exists; otherwise this establishes the convention).
- No `platformdirs` dependency. If the project ever adopts `platformdirs` for config, the log location can be migrated then.

Rotation: 1 MB per file, 3 backups. Cap is ~4 MB total, which is plenty for months of WARNING traffic on a personal tool.

## Testing

### Unit tests for `setup_logging`

`tests/test_logging_setup.py` (new file):

- **`test_setup_logging_creates_file`**: call `setup_logging()` with a monkeypatched log dir (`tmp_path`), emit a WARNING, flush, assert the file exists and contains the message.
- **`test_setup_logging_is_idempotent`**: call `setup_logging()` twice, assert only one `RotatingFileHandler` is attached to the root logger.
- **`test_setup_logging_ignores_debug_by_default`**: emit a DEBUG message, assert it does NOT appear in the file. Emit a WARNING, assert it does.

All three tests must restore the root logger state in a `finally` block (or via a pytest fixture) so they do not pollute other tests that inspect the logger.

### No unit tests for the warning call sites

The bare-except replacements are straightforward: "if the try block raises, log and return the fallback." Mocking `pygit2` well enough to verify the warning fires is more work than the coverage is worth — infrastructure tests already exercise happy paths, and the log-call sites are simple enough that visual diff review is sufficient. The manual acceptance step covers an end-to-end smoke test.

### Manual acceptance

1. Run the app on a real repo, confirm the file `~/.gitcrisp/logs/gitcrisp.log` is created on startup with no entries.
2. Trigger a known-failing path (for example, check out a branch with an unreadable submodule) and confirm a WARNING entry appears in the file.
3. Confirm the app behavior is unchanged — the same fallback (empty diff, empty list, etc.) is still returned.
4. Run the app about 20 times over a few sessions, confirm the log file does not grow beyond ~1 MB before rotating.

## File change list

**New:**
- `git_gui/logging_setup.py`
- `tests/test_logging_setup.py`

**Modified:**
- `main.py` — import and call `setup_logging()` at the top of `main()`.
- `git_gui/infrastructure/pygit2_repo.py` — add module logger; replace 12 bare-except sites with warning-logged versions.

## Out of scope

- In-app log viewer / menu item.
- Env-var-based debug level toggle.
- Log file path customisation.
- Sending Qt-internal messages through the logger.
- Replacing bare-except sites outside `pygit2_repo.py` (presentation layer has its own patterns that are not part of this spec).
- Reworking the `LogPanel` widget. It stays as user-facing operation status.
