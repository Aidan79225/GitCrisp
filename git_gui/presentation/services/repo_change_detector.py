# git_gui/presentation/services/repo_change_detector.py
"""Auto change detection for the active git repository.

Watches .git/ for external git-state writes and listens to application
focus changes for working-tree edit polling. Both sources funnel through
a 200 ms single-shot debouncer that calls the injected on_reload callback.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QFileSystemWatcher, QObject, Qt, QTimer
from PySide6.QtGui import QGuiApplication

logger = logging.getLogger(__name__)

_DEBOUNCE_MS = 200
_SELF_RELOAD_SUPPRESS_MS = 500


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

        self._suppress_until_ms: float = 0.0

    # ── Public API ──────────────────────────────────────────────────────

    def stop(self) -> None:
        """Disconnect and release watches. Idempotent."""
        app = QGuiApplication.instance()
        if app is not None:
            try:
                app.applicationStateChanged.disconnect(self._on_app_state_changed)
            except (RuntimeError, TypeError):
                pass  # Already disconnected.
        # Qt warns "removePaths: list is empty" if either argument is empty —
        # which happens when the watch list never got populated (e.g. the path
        # is a monorepo subdirectory with no .git/ of its own).
        files = self._watcher.files()
        if files:
            self._watcher.removePaths(files)
        directories = self._watcher.directories()
        if directories:
            self._watcher.removePaths(directories)
        self._debouncer.stop()

    def notify_self_reload(self) -> None:
        """Record that GitCrisp just triggered its own reload. Watcher events
        arriving within the next _SELF_RELOAD_SUPPRESS_MS are ignored, so
        in-app commits don't cause a duplicate reload from the filesystem
        events that our own writes produce."""
        self._suppress_until_ms = monotonic() * 1000.0 + _SELF_RELOAD_SUPPRESS_MS

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
            git_dir / "FETCH_HEAD",
            git_dir / "ORIG_HEAD",
            git_dir / "MERGE_HEAD",
            git_dir / "refs" / "stash",
        ]
        dirs = [
            git_dir,
            git_dir / "refs" / "heads",
            git_dir / "refs" / "remotes",
            git_dir / "refs" / "tags",
            git_dir / "logs",
            git_dir / "worktrees",
        ]

        for f in files:
            if f.is_file() and not self._watcher.addPath(str(f)):
                logger.warning("RepoChangeDetector: could not watch file %s", f)
        for d in dirs:
            if d.is_dir() and not self._watcher.addPath(str(d)):
                logger.warning("RepoChangeDetector: could not watch dir %s", d)

    # ── Handlers ────────────────────────────────────────────────────────

    def _schedule_reload(self, _path: str = "") -> None:
        """Coalesce filesystem events — each event restarts the debounce timer.
        If we're within a self-reload suppression window, drop the event."""
        if monotonic() * 1000.0 < self._suppress_until_ms:
            return
        self._debouncer.start()

    def _schedule_reload_force(self) -> None:
        """Same as _schedule_reload but never suppressed — used for focus events
        which are user-driven, not consequences of our own writes."""
        self._debouncer.start()

    def _on_app_state_changed(self, state: Qt.ApplicationState) -> None:
        if state == Qt.ApplicationActive:
            self._schedule_reload_force()

    def _fire_reload(self) -> None:
        """Timer fired — run the callback."""
        self._on_reload()
