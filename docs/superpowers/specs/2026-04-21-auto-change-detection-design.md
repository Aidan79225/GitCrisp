# Auto Change Detection — Design

**Date:** 2026-04-21
**Status:** Proposed

## Goal

Detect external changes to the active repository — both local git-state updates (commits / checkouts / fetches made outside the app) and working-tree edits (files saved by an external editor) — and refresh the UI automatically instead of requiring the user to press F5.

## Scope

- **A. Local git-state detection** via `QFileSystemWatcher` rooted in the active repo's `.git/` directory.
- **B. Working-tree edit detection** via `QApplication.applicationStateChanged` (focus-based polling): when the user tabs back into GitCrisp, trigger a reload so `is_dirty` + working-tree panel refresh.
- **One central debouncer** (200 ms) collapses event storms into a single reload.
- **Coarse-grained reload**: every detected change triggers `MainWindow._reload()` — the existing central sync.

## UX Decisions

| Concern | Decision |
|---|---|
| Detection mechanism for A (git state) | `QFileSystemWatcher` (built-in Qt). No new dependency. |
| Detection mechanism for B (workdir) | `QApplication.applicationStateChanged` on transition to `Qt.ApplicationActive`. No recursive file watcher. |
| Reload granularity | Coarse — `_reload()` always. Selective reload is premature optimization. |
| Debounce interval | 200 ms after the last event before reload fires. |
| Opt-out toggle | Not included in v1. Always on. Adding a preference checkbox is a <50 LOC follow-up. |
| Preference persistence | None (nothing to persist yet). |
| User notification | None — silent reload. |
| Cross-repo watching | Only the active repo. Previous detector destroyed on repo switch. |
| Repository lifecycle | Detector constructed in `_on_repo_ready` and destroyed in `_enter_empty_state` / at the start of `_on_repo_ready` for the next repo. |

## Approach

A single new presentation-layer service, `RepoChangeDetector`, is owned by `MainWindow`. It composes:

- A `QFileSystemWatcher` that watches a fixed list of files and directories inside `.git/`.
- A connection to `QApplication.instance().applicationStateChanged` that triggers on reactivation.
- A shared 200 ms `QTimer.singleShot` debouncer that collapses storms and finally calls the `on_reload` callback supplied by `MainWindow` (`self._reload`).

`MainWindow` constructs one detector per repo session and replaces it on repo switch. No mixin, no shared state, no new ports — it's a leaf service.

## Architecture & files touched

**New files:**
```
git_gui/presentation/services/
├── __init__.py
└── repo_change_detector.py          # RepoChangeDetector class

tests/presentation/services/
├── __init__.py
├── test_repo_change_detector_debounce.py
├── test_repo_change_detector_watcher.py
└── test_repo_change_detector_focus.py
```

**Modified files:**
- `git_gui/presentation/main_window/repo_lifecycle.py` — construct `RepoChangeDetector` in `_on_repo_ready`; destroy previous instance before constructing a new one; destroy on `_enter_empty_state`.

**Not touched:** domain, application, infrastructure, other mixins, child widgets, theme, QSS, README.

## `RepoChangeDetector` — API

```python
# git_gui/presentation/services/repo_change_detector.py
from __future__ import annotations
import logging
from pathlib import Path
from typing import Callable
from PySide6.QtCore import QObject, QTimer, Qt
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
        from PySide6.QtCore import QFileSystemWatcher
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
        """Add every file and directory inside .git/ that indicates a
        state change. Missing paths are silently skipped (a fresh repo
        has no refs/remotes/, etc.)."""
        git_dir = self._repo_path / ".git"
        if not git_dir.is_dir():
            logger.warning("RepoChangeDetector: .git not found at %s", git_dir)
            return

        # Specific files — caught when their contents are rewritten.
        files = [
            git_dir / "HEAD",
            git_dir / "index",
            git_dir / "packed-refs",
        ]
        # Specific directories — caught when entries are added/removed/renamed.
        dirs = [
            git_dir,                     # catches MERGE_HEAD, CHERRY_PICK_HEAD, REVERT_HEAD lifecycle
            git_dir / "refs" / "heads",
            git_dir / "refs" / "remotes",
            git_dir / "refs" / "tags",
            git_dir / "logs",            # any HEAD-changing op writes here
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

Key points:
- `QFileSystemWatcher.addPath` returns `False` on failure (missing path, OS limit). Logged at `warning`; not fatal.
- `_schedule_reload` accepts the watcher's path arg (for the signal signature) but ignores it — all reloads are coarse.
- `_on_app_state_changed` fires on any app-state transition; we filter for `Qt.ApplicationActive` (re-focus).
- `stop()` is idempotent and safe to call multiple times. Re-disconnecting a signal throws; we swallow.

## `MainWindow` integration

In `git_gui/presentation/main_window/repo_lifecycle.py`:

1. Add `self._change_detector: RepoChangeDetector | None = None` to `MainWindow.__init__` (in `main_window/main_window.py`, alongside the other instance-attribute assignments). Mixins have no `__init__`, so the attribute lives on the composite.
2. In `_on_repo_ready`:
   - Before swapping buses and wiring widgets, call `self._stop_change_detector()`.
   - After the main body, construct `RepoChangeDetector(path, self._reload, parent=self)` and store on `self._change_detector`.
3. In `_enter_empty_state`: call `self._stop_change_detector()` and set `self._change_detector = None`.
4. Helper `_stop_change_detector` inside `RepoLifecycleMixin`:
   ```python
   def _stop_change_detector(self) -> None:
       if self._change_detector is not None:
           self._change_detector.stop()
           self._change_detector.deleteLater()
           self._change_detector = None
   ```
5. Add `self._change_detector: RepoChangeDetector | None = None` to `MainWindow.__init__` in `main_window/main_window.py`, alongside the other instance attributes.

Import `RepoChangeDetector` inside `repo_lifecycle.py`:
```python
from git_gui.presentation.services.repo_change_detector import RepoChangeDetector
```

## Preventing spurious reloads from our own actions

When GitCrisp itself makes a commit, it modifies `.git/HEAD`, `.git/index`, etc. Those writes will fire `QFileSystemWatcher` events, which will debounce into a reload — but `MainWindow._on_commit`-style handlers already call `self._reload()` explicitly after the action. So the detector triggers a second reload 200 ms later.

This is harmless — `_reload()` is idempotent and fast — but it does mean every in-app mutation causes 2 reloads instead of 1. Acceptable for v1. If profiling ever shows it matters, we can add a "suspend-for-N-ms" hook around in-app writes.

## Error handling

- `RepoChangeDetector.__init__` gracefully handles missing `.git/` (logs warning, proceeds with empty watch set).
- `QFileSystemWatcher.addPath` failures are logged, not raised.
- `stop()` handles already-disconnected signals (`try/except RuntimeError, TypeError`).
- `MainWindow._reload()` raising is not caught by the detector — existing per-widget error handling deals with it.

## Testing

**`test_repo_change_detector_debounce.py`** (pytest-qt):
- Fire 5 calls to `_schedule_reload` within 50 ms; assert callback fires exactly once after ~200 ms. Use `qtbot.wait(300)` and a counter callback.
- Fire one call; assert callback fires at ~200 ms, not immediately.

**`test_repo_change_detector_watcher.py`** (pytest-qt, requires `repo_path` fixture from `tests/conftest.py`):
- Construct `RepoChangeDetector(repo_path, callback)`.
- Assert `watcher.files()` includes `.git/HEAD` (and whatever else exists at construction time).
- Assert `watcher.directories()` includes `.git/` and `.git/refs/heads/`.
- Overwrite `.git/HEAD` with new content (e.g., `head_path.write_text("ref: refs/heads/other\n")`) — `QFileSystemWatcher.fileChanged` fires on content modification, not on pure mtime touches. `qtbot.wait(300)`; assert callback was invoked.

**`test_repo_change_detector_focus.py`** (pytest-qt):
- Construct detector; connect a counter callback.
- `QGuiApplication.instance().applicationStateChanged.emit(Qt.ApplicationActive)`.
- `qtbot.wait(300)`; assert callback fired once.
- Emit `Qt.ApplicationInactive`; `qtbot.wait(300)`; assert callback did NOT fire a second time.

**No tests** for the `MainWindow` wiring itself — the existing `_on_repo_ready` and `_enter_empty_state` tests cover that the repo-switch flow works; adding the detector doesn't change their assertions.

## Out of scope

- **Auto-fetch** (option C from brainstorming). Periodic network activity is a separate design concern.
- **Recursive workdir file watcher** (B-option-2). Focus-based polling is sufficient for v1.
- **Selective reload** by event kind (ref change → graph only, index change → working-tree only). Premature optimization.
- **User-configurable debounce interval** or opt-out toggle.
- **Notifications** to the user when external changes are detected (just silently reload).
- **Watching multiple repos** simultaneously. Only the currently active repo is watched.
- **Suspending the detector** during in-app writes to prevent duplicate reloads.
- **Retrying failed `addPath` calls** on OS-limit / non-existent files.
- **Cross-platform testing** beyond the existing CI surface.
