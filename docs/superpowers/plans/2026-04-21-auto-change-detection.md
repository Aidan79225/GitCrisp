# Auto Change Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect external changes to the active repository — local git-state writes via `QFileSystemWatcher` on `.git/` and working-tree edits via `QApplication.applicationStateChanged` — and reload the UI automatically after a 200 ms debounce.

**Architecture:** One new presentation-layer service `RepoChangeDetector` under `git_gui/presentation/services/`. Watches a fixed set of files/directories inside `.git/`, plus the application's focus state. Both sources funnel through a single-shot `QTimer` debouncer that calls an injected `on_reload` callback. `MainWindow` constructs one detector per active repo in `_on_repo_ready` and destroys it on `_enter_empty_state` or on the next repo switch.

**Tech Stack:** Python 3.13, PySide6 (Qt), pytest + pytest-qt.

**Spec:** `docs/superpowers/specs/2026-04-21-auto-change-detection-design.md`

---

## File Structure

**New files:**
- `git_gui/presentation/services/__init__.py` (empty marker)
- `git_gui/presentation/services/repo_change_detector.py` — `RepoChangeDetector` class
- `tests/presentation/services/__init__.py` (empty marker — check if pre-existing)
- `tests/presentation/services/test_repo_change_detector_debounce.py`
- `tests/presentation/services/test_repo_change_detector_watcher.py`
- `tests/presentation/services/test_repo_change_detector_focus.py`

**Modified files:**
- `git_gui/presentation/main_window/main_window.py` — add `self._change_detector: RepoChangeDetector | None = None` in `__init__`.
- `git_gui/presentation/main_window/repo_lifecycle.py` — import detector; construct in `_on_repo_ready`; destroy in `_enter_empty_state` and before each new repo-ready wiring; add `_stop_change_detector` helper.

**Not touched:** domain, application, infrastructure, child widgets, theme, QSS, README.

---

## Task 1: `RepoChangeDetector` service (TDD)

Create the service class and three focused test files. Commit scaffold + tests + implementation together once tests pass.

**Files:**
- Create: `git_gui/presentation/services/__init__.py`
- Create: `git_gui/presentation/services/repo_change_detector.py`
- Create: `tests/presentation/services/__init__.py` (skip if exists)
- Create: `tests/presentation/services/test_repo_change_detector_debounce.py`
- Create: `tests/presentation/services/test_repo_change_detector_watcher.py`
- Create: `tests/presentation/services/test_repo_change_detector_focus.py`

- [ ] **Step 1: Create empty package markers**

Write `git_gui/presentation/services/__init__.py`:
```python
# git_gui/presentation/services/__init__.py
```

Check if `tests/presentation/services/__init__.py` exists via `ls tests/presentation/services/__init__.py 2>/dev/null`. If it doesn't, create it with the same single-comment-line body:
```python
# tests/presentation/services/__init__.py
```

- [ ] **Step 2: Write the debounce test file**

Create `tests/presentation/services/test_repo_change_detector_debounce.py`:

```python
"""Debounce behaviour of RepoChangeDetector — events within 200 ms coalesce
into a single reload callback."""
from __future__ import annotations
import pytest

from git_gui.presentation.services.repo_change_detector import RepoChangeDetector


@pytest.fixture
def detector(qtbot, tmp_path):
    """Construct a detector rooted in an empty temp directory. The .git/
    watch paths all fail to add (dir missing), which is fine — we exercise
    only the debouncer here."""
    calls: list[None] = []
    d = RepoChangeDetector(str(tmp_path), on_reload=lambda: calls.append(None))
    # RepoChangeDetector is a plain QObject, not a QWidget, so don't
    # register with qtbot.addWidget — the fixture holding the reference
    # keeps it alive for the test's duration.
    yield d, calls
    d.stop()


def test_single_event_triggers_one_reload_after_debounce(detector, qtbot):
    d, calls = detector
    d._schedule_reload()
    # Immediately: not yet fired.
    assert calls == []
    # After 300 ms: fired exactly once.
    qtbot.wait(300)
    assert len(calls) == 1


def test_multiple_events_within_debounce_window_coalesce_into_one_reload(detector, qtbot):
    d, calls = detector
    for _ in range(5):
        d._schedule_reload()
        qtbot.wait(30)  # 5 events across 150 ms — still within the 200 ms window
    # At this point the debouncer has been restarted each time; nothing fired yet.
    assert calls == []
    qtbot.wait(300)
    # Only one reload fired after the storm settled.
    assert len(calls) == 1


def test_events_separated_by_longer_than_debounce_fire_separately(detector, qtbot):
    d, calls = detector
    d._schedule_reload()
    qtbot.wait(300)
    assert len(calls) == 1
    d._schedule_reload()
    qtbot.wait(300)
    assert len(calls) == 2


def test_stop_cancels_pending_reload(detector, qtbot):
    d, calls = detector
    d._schedule_reload()
    # Before the timer fires, stop the detector.
    d.stop()
    qtbot.wait(300)
    # No reload should have fired.
    assert calls == []
```

- [ ] **Step 3: Write the watcher test file**

Create `tests/presentation/services/test_repo_change_detector_watcher.py`:

```python
"""QFileSystemWatcher set-up and fileChanged → reload propagation."""
from __future__ import annotations
import pytest

from git_gui.presentation.services.repo_change_detector import RepoChangeDetector


def test_detector_watches_git_head_and_refs_heads(qtbot, repo_path):
    """Given a real temp git repo (from conftest), the detector should
    register at least HEAD and refs/heads/ as watch targets."""
    calls: list[None] = []
    d = RepoChangeDetector(str(repo_path), on_reload=lambda: calls.append(None))

    watched_files = set(d._watcher.files())
    watched_dirs = set(d._watcher.directories())

    assert any(f.endswith("HEAD") for f in watched_files), (
        f"expected HEAD in watched files, got {watched_files}"
    )
    assert any(dir_.endswith("refs/heads") or dir_.endswith("refs\\heads")
               for dir_ in watched_dirs), (
        f"expected refs/heads in watched dirs, got {watched_dirs}"
    )


def test_rewriting_head_triggers_reload_after_debounce(qtbot, repo_path):
    """Overwriting .git/HEAD content should fire the debounced reload."""
    calls: list[None] = []
    d = RepoChangeDetector(str(repo_path), on_reload=lambda: calls.append(None))

    head_path = repo_path / ".git" / "HEAD"
    # Overwrite with new content — mtime-only touches don't always fire
    # QFileSystemWatcher.fileChanged on all platforms.
    head_path.write_text("ref: refs/heads/other\n", encoding="utf-8")

    qtbot.wait(400)
    assert len(calls) >= 1, (
        "reload callback should fire after .git/HEAD is rewritten"
    )


def test_missing_git_dir_does_not_crash(qtbot, tmp_path):
    """Constructing against a non-git directory should log a warning but
    not raise."""
    calls: list[None] = []
    d = RepoChangeDetector(str(tmp_path), on_reload=lambda: calls.append(None))

    # Empty watch set — nothing to watch.
    assert d._watcher.files() == []
    assert d._watcher.directories() == []


def test_stop_releases_all_watches(qtbot, repo_path):
    calls: list[None] = []
    d = RepoChangeDetector(str(repo_path), on_reload=lambda: calls.append(None))

    assert len(d._watcher.files()) + len(d._watcher.directories()) > 0

    d.stop()

    assert d._watcher.files() == []
    assert d._watcher.directories() == []
```

Note: `repo_path` is the pre-existing fixture from `tests/conftest.py:17` that builds a real tmp git repo with one commit on `master`.

- [ ] **Step 4: Write the focus test file**

Create `tests/presentation/services/test_repo_change_detector_focus.py`:

```python
"""applicationStateChanged → reload propagation."""
from __future__ import annotations
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

from git_gui.presentation.services.repo_change_detector import RepoChangeDetector


def test_application_becoming_active_triggers_reload(qtbot, tmp_path):
    calls: list[None] = []
    d = RepoChangeDetector(str(tmp_path), on_reload=lambda: calls.append(None))

    # Simulate the app gaining focus.
    QGuiApplication.instance().applicationStateChanged.emit(Qt.ApplicationActive)

    qtbot.wait(300)
    assert len(calls) == 1


def test_application_going_inactive_does_not_trigger_reload(qtbot, tmp_path):
    calls: list[None] = []
    d = RepoChangeDetector(str(tmp_path), on_reload=lambda: calls.append(None))

    QGuiApplication.instance().applicationStateChanged.emit(Qt.ApplicationInactive)

    qtbot.wait(300)
    assert calls == []


def test_stop_disconnects_focus_signal(qtbot, tmp_path):
    calls: list[None] = []
    d = RepoChangeDetector(str(tmp_path), on_reload=lambda: calls.append(None))

    d.stop()

    QGuiApplication.instance().applicationStateChanged.emit(Qt.ApplicationActive)
    qtbot.wait(300)
    assert calls == []
```

- [ ] **Step 5: Run the new tests to confirm red**

Run: `uv run pytest tests/presentation/services/ -v`

Expected: ALL tests FAIL with `ModuleNotFoundError: No module named 'git_gui.presentation.services.repo_change_detector'`.

- [ ] **Step 6: Implement the service**

Create `git_gui/presentation/services/repo_change_detector.py`:

```python
# git_gui/presentation/services/repo_change_detector.py
"""Auto change detection for the active git repository.

Watches .git/ for external git-state writes and listens to application
focus changes for working-tree edit polling. Both sources funnel through
a 200 ms single-shot debouncer that calls the injected on_reload callback.
"""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Callable
from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Qt
from PySide6.QtGui import QGuiApplication

logger = logging.getLogger(__name__)

_DEBOUNCE_MS = 200


class RepoChangeDetector(QObject):
    """Watch .git/ for external changes and GitCrisp's own focus state.
    Call `on_reload` after a short debounce when either source fires.

    Lifecycle: construct per active repo via `RepoChangeDetector(path, callback)`.
    Call `stop()` before discarding to disconnect the application-state signal
    and release filesystem-watch handles.
    """

    def __init__(
        self,
        repo_path: str,
        on_reload: Callable[[], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._repo_path = Path(repo_path)
        self._on_reload = on_reload

        # Debouncer — single-shot timer, restarted on each event.
        self._debouncer = QTimer(self)
        self._debouncer.setSingleShot(True)
        self._debouncer.setInterval(_DEBOUNCE_MS)
        self._debouncer.timeout.connect(self._fire_reload)

        # Git-state watcher.
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._schedule_reload)
        self._watcher.directoryChanged.connect(self._schedule_reload)
        self._add_git_watch_paths()

        # Focus watcher.
        app = QGuiApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._on_app_state_changed)

    # ── Public API ──────────────────────────────────────────────────────

    def stop(self) -> None:
        """Disconnect and release watches. Idempotent."""
        app = QGuiApplication.instance()
        if app is not None:
            try:
                app.applicationStateChanged.disconnect(self._on_app_state_changed)
            except (RuntimeError, TypeError):
                pass  # Already disconnected.
        self._watcher.removePaths(self._watcher.files())
        self._watcher.removePaths(self._watcher.directories())
        self._debouncer.stop()

    # ── Watch-set setup ─────────────────────────────────────────────────

    def _add_git_watch_paths(self) -> None:
        """Add every file and directory inside .git/ that indicates a state
        change. Missing paths are silently skipped."""
        git_dir = self._repo_path / ".git"
        if not git_dir.is_dir():
            logger.warning("RepoChangeDetector: .git not found at %s", git_dir)
            return

        files = [
            git_dir / "HEAD",
            git_dir / "index",
            git_dir / "packed-refs",
        ]
        dirs = [
            git_dir,
            git_dir / "refs" / "heads",
            git_dir / "refs" / "remotes",
            git_dir / "refs" / "tags",
            git_dir / "logs",
        ]

        for f in files:
            if f.is_file() and not self._watcher.addPath(str(f)):
                logger.warning("RepoChangeDetector: could not watch file %s", f)
        for d in dirs:
            if d.is_dir() and not self._watcher.addPath(str(d)):
                logger.warning("RepoChangeDetector: could not watch dir %s", d)

    # ── Handlers ────────────────────────────────────────────────────────

    def _schedule_reload(self, _path: str = "") -> None:
        """Coalesce events — each event restarts the debounce timer."""
        self._debouncer.start()

    def _on_app_state_changed(self, state: Qt.ApplicationState) -> None:
        if state == Qt.ApplicationActive:
            self._schedule_reload()

    def _fire_reload(self) -> None:
        """Timer fired — run the callback."""
        self._on_reload()
```

- [ ] **Step 7: Run the new tests to confirm green**

Run: `uv run pytest tests/presentation/services/ -v`

Expected: ALL tests PASS (11 total: 4 debounce + 4 watcher + 3 focus).

If the watcher test `test_rewriting_head_triggers_reload_after_debounce` is flaky on your platform, it may need a longer wait — try `qtbot.wait(1000)` instead of `400`. `QFileSystemWatcher.fileChanged` delivery latency varies on Windows vs macOS vs Linux. If it fails consistently, investigate before proceeding.

- [ ] **Step 8: Run the full suite to confirm no regressions**

Run: `uv run pytest tests/ -q`

Expected: **532 passed** (521 baseline + 11 new).

- [ ] **Step 9: Commit**

```bash
git add git_gui/presentation/services/ tests/presentation/services/
git commit -m "feat(services): add RepoChangeDetector for .git/ and focus-based auto-reload"
```

---

## Task 2: Wire `RepoChangeDetector` into `MainWindow`

Integrate the service into the repo lifecycle. `_on_repo_ready` constructs a detector; `_enter_empty_state` and the next `_on_repo_ready` destroy the previous instance.

**Files:**
- Modify: `git_gui/presentation/main_window/main_window.py`
- Modify: `git_gui/presentation/main_window/repo_lifecycle.py`

- [ ] **Step 1: Add the attribute to `MainWindow.__init__`**

In `git_gui/presentation/main_window/main_window.py`, find the block of instance-attribute assignments inside `__init__` (near the top, right after `super().__init__(parent)` or after `self._session_factory = session_factory`). Add:

```python
        self._change_detector = None  # RepoChangeDetector | None
```

Place it alongside `self._remote_running = False` and `self._selected_oid = None` — it's instance state, not a widget. Use `None` as the initial value (no detector until a repo is loaded).

Do NOT import `RepoChangeDetector` in `main_window.py` — the type annotation is a string comment, and the mixin that uses it does the import.

- [ ] **Step 2: Import `RepoChangeDetector` in `repo_lifecycle.py`**

At the top of `git_gui/presentation/main_window/repo_lifecycle.py`, add:

```python
from git_gui.presentation.services.repo_change_detector import RepoChangeDetector
```

Place it alongside the existing imports (e.g., near `from PySide6.QtCore import QObject, Signal`).

- [ ] **Step 3: Add a `_stop_change_detector` helper method to `RepoLifecycleMixin`**

In `git_gui/presentation/main_window/repo_lifecycle.py`, inside `class RepoLifecycleMixin:`, add this helper method (place it above `_switch_repo` or wherever convenient):

```python
    def _stop_change_detector(self) -> None:
        """Stop and release the current change detector, if any."""
        if self._change_detector is not None:
            self._change_detector.stop()
            self._change_detector.deleteLater()
            self._change_detector = None
```

- [ ] **Step 4: Construct the detector in `_on_repo_ready`**

Find `_on_repo_ready` in `repo_lifecycle.py`. The method currently wires all child widgets to the new buses and updates window title + menu. At the END of the method body (after all existing wiring, just before the method returns), add:

```python
        # Replace any previous detector and start watching this repo.
        self._stop_change_detector()
        self._change_detector = RepoChangeDetector(
            repo_path=path, on_reload=self._reload, parent=self,
        )
```

`path` is the first argument of `_on_repo_ready(self, path, queries, commands)`.
`self._reload` comes from `ReloadCoordinatorMixin`.
`parent=self` parents the `QObject` to the `MainWindow` for automatic cleanup on window close.

- [ ] **Step 5: Stop the detector in `_enter_empty_state`**

Find `_enter_empty_state` in `repo_lifecycle.py`. At the top of the method body (before any existing work), add:

```python
        self._stop_change_detector()
```

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest tests/ -q`

Expected: **532 passed** (same as after Task 1 — integration doesn't add new tests; it just has to not break existing ones).

Key tests to verify green: `tests/presentation/test_main_window_session_factory.py`, `tests/presentation/test_main_window_checkout_conflict.py`, and the 11 new services tests.

- [ ] **Step 7: Manual smoke check**

Run: `uv run python main.py`

Open a repo. In a separate terminal, `cd` to the repo and run `git commit --allow-empty -m "external commit"`. Within ~500 ms, GitCrisp's graph should refresh and show the new commit without pressing F5. Then tab away from GitCrisp, save a file in your editor in that repo, tab back — the working-tree panel should refresh.

If the smoke fails, check logs (`~/.gitcrisp/logs/gitcrisp.log`) for `RepoChangeDetector` warnings about failed `addPath` calls.

- [ ] **Step 8: Commit**

```bash
git add git_gui/presentation/main_window/main_window.py git_gui/presentation/main_window/repo_lifecycle.py
git commit -m "feat(main_window): wire RepoChangeDetector for auto-reload on external changes"
```

---

## Done

After Task 2, auto change detection is live. Final state:

- External `git commit` / `git checkout` / `git fetch` / ref edits in the active repo trigger a reload within 200 ms.
- Tabbing back to GitCrisp after editing a file elsewhere triggers a reload.
- Repo switches correctly tear down the previous detector and start a new one.
- 532 tests pass (521 baseline + 11 new).
- No new runtime dependency.
