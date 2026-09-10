# MainWindow Session Factory + Tag-Cache Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove `main_window.py`'s direct import of `Pygit2Repository` by injecting a `session_factory` callable, and replace two silent `except Exception: pass` blocks in the tag-cache code with `logger.warning` calls.

**Architecture:** `main.py` remains the composition root and gains a local `_open_session(path)` helper that wraps the existing three-line `Pygit2Repository` + bus wiring. `MainWindow` accepts this helper as a required keyword-only constructor argument and invokes it from `_switch_repo` instead of constructing a repo directly. The two tag-cache exception blocks become `logger.warning` calls with actionable messages.

**Tech Stack:** Python 3.13, PySide6 (Qt), pytest + pytest-qt.

**Spec:** `docs/superpowers/specs/2026-04-17-main-window-session-factory-design.md`

---

## File Structure

**New files:**
- `tests/presentation/test_main_window_session_factory.py` — regression tests for factory injection, failure path, and no-infrastructure-import guard.

**Modified files:**
- `main.py` — add `_open_session(path)` helper; use it in the initial open path and pass it to `MainWindow`.
- `git_gui/presentation/main_window.py` — drop the `Pygit2Repository` import; add `session_factory` keyword-only parameter; refactor `_switch_repo` worker; add module-level `logger`; replace two `except Exception: pass` blocks with `logger.warning`.
- `tests/presentation/test_main_window_checkout_conflict.py` — pass a stub `session_factory` when constructing `MainWindow` (single-line update).

**Not touched:** domain, application, infrastructure, any widget other than `main_window.py`.

---

## Task 1: Inject `session_factory` into `MainWindow` (TDD)

Introduce a regression test suite first, then refactor both `main.py` and `main_window.py` together, finally fix the one existing test that constructs `MainWindow` positionally. Everything commits in one green step to keep the tree bisectable.

**Files:**
- Create: `tests/presentation/test_main_window_session_factory.py`
- Modify: `main.py`
- Modify: `git_gui/presentation/main_window.py`
- Modify: `tests/presentation/test_main_window_checkout_conflict.py`

- [ ] **Step 1: Write failing regression tests**

Create `tests/presentation/test_main_window_session_factory.py`:

```python
"""Regression tests for the session_factory injection — verifies
MainWindow never imports infrastructure directly and delegates repo
opening to an injected callable."""
from __future__ import annotations

import pathlib
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from git_gui.presentation.main_window import MainWindow


def _dummy_store() -> MagicMock:
    store = MagicMock()
    store.get_open_repos.return_value = []
    store.get_recent_repos.return_value = []
    store.get_active.return_value = None
    return store


def _make_window(qtbot, factory) -> MainWindow:
    win = MainWindow(
        queries=None,
        commands=None,
        repo_store=_dummy_store(),
        session_factory=factory,
    )
    qtbot.addWidget(win)
    return win


def test_switch_repo_invokes_session_factory(qtbot):
    """_switch_repo must call the injected factory on a worker thread and
    emit `ready` with the factory's return values."""
    fake_queries = MagicMock(name="queries")
    fake_commands = MagicMock(name="commands")
    factory = MagicMock(return_value=(fake_queries, fake_commands))

    win = _make_window(qtbot, factory)

    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=2000) as blocker:
        win._switch_repo("/some/path")

    assert factory.call_count == 1
    assert factory.call_args.args == ("/some/path",)
    path, queries, commands = blocker.args
    assert path == "/some/path"
    assert queries is fake_queries
    assert commands is fake_commands


def test_switch_repo_factory_failure_emits_failed_signal(qtbot):
    """If the factory raises, MainWindow emits `failed` with the error
    string — no exception escapes the worker."""
    factory = MagicMock(side_effect=RuntimeError("boom"))

    win = _make_window(qtbot, factory)

    with qtbot.waitSignal(win._repo_ready_signals.failed, timeout=2000) as blocker:
        win._switch_repo("/broken/path")

    path, error = blocker.args
    assert path == "/broken/path"
    assert "boom" in error


def test_main_window_source_does_not_import_infrastructure():
    """Regression guard: main_window.py must not reference
    git_gui.infrastructure in any import form."""
    source_path = pathlib.Path("git_gui/presentation/main_window.py")
    source = source_path.read_text(encoding="utf-8")
    assert "git_gui.infrastructure" not in source, (
        "main_window.py must not import from git_gui.infrastructure — "
        "use the injected session_factory instead."
    )
```

- [ ] **Step 2: Run the new tests to confirm red**

Run: `uv run pytest tests/presentation/test_main_window_session_factory.py -v`

Expected: all three tests FAIL. Likely failure modes:
- `test_switch_repo_invokes_session_factory` and `test_switch_repo_factory_failure_emits_failed_signal` fail with `TypeError: __init__() got an unexpected keyword argument 'session_factory'`.
- `test_main_window_source_does_not_import_infrastructure` fails with `AssertionError` because the source still has the Pygit2Repository import.

- [ ] **Step 3: Add the `_open_session` helper to `main.py`**

In `main.py`, immediately before `def main() -> None:` (currently around line 56), insert:

```python
def _open_session(path: str) -> tuple[QueryBus, CommandBus]:
    repo = Pygit2Repository(path)
    return QueryBus.from_reader(repo), CommandBus.from_writer(repo)
```

- [ ] **Step 4: Use `_open_session` for the initial repo open in `main.py`**

In `main.py`, find the three-line block (currently lines 81-83):

```python
    repo = Pygit2Repository(repo_path)
    queries = QueryBus.from_reader(repo)
    commands = CommandBus.from_writer(repo)
```

Replace with:

```python
    queries, commands = _open_session(repo_path)
```

- [ ] **Step 5: Pass the factory to `MainWindow` in `main.py`**

In `main.py`, find the `MainWindow(...)` call (currently line 85):

```python
    window = MainWindow(queries, commands, repo_store, remote_tag_cache, repo_path)
```

Replace with:

```python
    window = MainWindow(
        queries, commands, repo_store, remote_tag_cache, repo_path,
        session_factory=_open_session,
    )
```

- [ ] **Step 6: Drop the `Pygit2Repository` import from `main_window.py`**

In `git_gui/presentation/main_window.py`, delete line 12:

```python
from git_gui.infrastructure.pygit2_repo import Pygit2Repository
```

- [ ] **Step 7: Add the `Callable` import in `main_window.py`**

In `git_gui/presentation/main_window.py`, at the top of the file, add this import near the other stdlib imports (around line 4):

```python
from typing import Callable
```

The final top-of-file import block should look like:

```python
# git_gui/presentation/main_window.py
from __future__ import annotations
import threading
from typing import Callable
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog, QInputDialog, QMainWindow, QMessageBox, QSplitter, QStackedWidget,
    QVBoxLayout, QWidget,
)
from git_gui.domain.entities import WORKING_TREE_OID, ResetMode
from git_gui.domain.ports import IRepoStore
from git_gui.presentation.bus import CommandBus, QueryBus
# ... (remaining imports unchanged)
```

- [ ] **Step 8: Extend `MainWindow.__init__` to accept `session_factory`**

In `git_gui/presentation/main_window.py`, find the current signature (lines 42-43):

```python
class MainWindow(QMainWindow):
    def __init__(self, queries: QueryBus | None, commands: CommandBus | None,
                 repo_store: IRepoStore, remote_tag_cache=None, repo_path: str | None = None, parent=None) -> None:
```

Replace with:

```python
class MainWindow(QMainWindow):
    def __init__(self, queries: QueryBus | None, commands: CommandBus | None,
                 repo_store: IRepoStore, remote_tag_cache=None, repo_path: str | None = None, parent=None,
                 *, session_factory: Callable[[str], tuple[QueryBus, CommandBus]]) -> None:
```

Inside `__init__`, immediately after `self._repo_path = repo_path` (currently line 57), add:

```python
        self._session_factory = session_factory
```

- [ ] **Step 9: Refactor the `_switch_repo` worker**

In `git_gui/presentation/main_window.py`, find `_switch_repo` (currently around line 713) and its worker:

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

Replace with:

```python
        def _worker():
            try:
                queries, commands = self._session_factory(path)
                signals.ready.emit(path, queries, commands)
            except Exception as e:
                signals.failed.emit(path, str(e))
```

- [ ] **Step 10: Update the existing test that constructs `MainWindow`**

In `tests/presentation/test_main_window_checkout_conflict.py`, find line 14:

```python
    win = MainWindow(queries=None, commands=None, repo_store=repo_store)
```

Replace with:

```python
    win = MainWindow(
        queries=None, commands=None, repo_store=repo_store,
        session_factory=lambda _p: (MagicMock(), MagicMock()),
    )
```

`MagicMock` is already imported at the top of that file (`from unittest.mock import MagicMock, patch`), so no new import is needed.

- [ ] **Step 11: Run the new tests to confirm green**

Run: `uv run pytest tests/presentation/test_main_window_session_factory.py -v`

Expected: all three tests PASS.

- [ ] **Step 12: Run the existing checkout-conflict test**

Run: `uv run pytest tests/presentation/test_main_window_checkout_conflict.py -v`

Expected: all existing tests PASS.

- [ ] **Step 13: Run the full suite**

Run: `uv run pytest tests/ -q`

Expected: no regressions. If any test fails because it constructs `MainWindow` without `session_factory`, update it in the same pattern as Step 10.

- [ ] **Step 14: Commit**

```bash
git add main.py git_gui/presentation/main_window.py tests/presentation/test_main_window_session_factory.py tests/presentation/test_main_window_checkout_conflict.py
git commit -m "refactor(main_window): inject session_factory, drop direct infrastructure import"
```

---

## Task 2: Replace silent `except Exception: pass` with `logger.warning`

Add module-level logging to `main_window.py` and convert the two tag-cache failure paths from silent swallowing to actionable warnings. No new test — the spec explicitly excludes log-message text from the contract.

**Files:**
- Modify: `git_gui/presentation/main_window.py`

- [ ] **Step 1: Add `import logging` and module-level `logger`**

In `git_gui/presentation/main_window.py`, update the top-of-file imports (currently line 3):

```python
import threading
```

Replace with:

```python
import logging
import threading
```

Then, immediately after the top import block and **before** the `class _RemoteSignals(QObject):` definition (currently around line 30), add:

```python
logger = logging.getLogger(__name__)
```

- [ ] **Step 2: Replace the first silent except in `_on_delete_tag`**

In `git_gui/presentation/main_window.py`, find the block in `_on_delete_tag` (currently around lines 596-603):

```python
        if self._remote_tag_cache and self._repo_path:
            try:
                cache_data = self._remote_tag_cache.load(self._repo_path)
                for remote, names in cache_data.items():
                    if name in names:
                        remotes_with_tag.append(remote)
            except Exception:
                pass
```

Replace the `except Exception: pass` with:

```python
            except Exception as e:
                logger.warning(
                    "Remote tag cache load failed for %s: %s",
                    self._repo_path, e,
                )
```

The full block should now read:

```python
        if self._remote_tag_cache and self._repo_path:
            try:
                cache_data = self._remote_tag_cache.load(self._repo_path)
                for remote, names in cache_data.items():
                    if name in names:
                        remotes_with_tag.append(remote)
            except Exception as e:
                logger.warning(
                    "Remote tag cache load failed for %s: %s",
                    self._repo_path, e,
                )
```

- [ ] **Step 3: Replace the second silent except in `_delete_tag_local_and_remote._fn`**

In `git_gui/presentation/main_window.py`, find the block inside `_fn` (currently around lines 659-666):

```python
                if self._remote_tag_cache and self._repo_path:
                    try:
                        data = self._remote_tag_cache.load(self._repo_path)
                        if r in data and name in data[r]:
                            data[r] = [t for t in data[r] if t != name]
                            self._remote_tag_cache.save(self._repo_path, data)
                    except Exception:
                        pass
```

Replace the `except Exception: pass` with:

```python
                    except Exception as e:
                        logger.warning(
                            "Remote tag cache update failed for %s (remote=%s, tag=%s): %s",
                            self._repo_path, r, name, e,
                        )
```

The full block should now read:

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

- [ ] **Step 4: Verify the remaining bare-`except Exception:` sites are the expected two**

Run: `grep -n "except Exception:" git_gui/presentation/main_window.py` (or use the Grep tool).

Expected: exactly two matches remain:
- Line ~245 — state-banner fall-through (has a recovery action, NOT a silent pass; leave it).
- Line ~958 — documented cache-update failure with the inline comment `# cache update failure is non-critical` (leave it).

If a third `except Exception:` with a bare `pass` is present in main_window.py, the edit in Step 2 or Step 3 didn't land — re-apply it.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest tests/ -q`

Expected: no regressions. The two converted exception paths are not exercised by existing tests, so behavior is unchanged from the test suite's perspective — only log output changes.

- [ ] **Step 6: Commit**

```bash
git add git_gui/presentation/main_window.py
git commit -m "fix(main_window): log tag-cache failures instead of swallowing"
```

---

## Done

After Task 2 commit, sub-project A is complete. Five remaining sub-projects (B, C, D) are tracked separately.
