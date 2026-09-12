"""Auto change detection for the active git repository.

Watches the repository's git directories for external git-state writes and
listens to application focus changes for working-tree edit polling. Both
sources funnel through a 200 ms single-shot debouncer that calls the injected
on_reload callback.

"Directories", plural: a linked worktree keeps its HEAD and index apart from
the refs and objects it shares with the repo it was made from, so watching one
place is enough only in an ordinary clone.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QFileSystemWatcher, QObject, Qt, QTimer
from PySide6.QtGui import QGuiApplication

logger = logging.getLogger(__name__)

_DEBOUNCE_MS = 200
_SELF_RELOAD_SUPPRESS_MS = 500

# The names that mean "git state moved". Each is looked for in both git
# directories below, because in a worktree they are split across the two.
_WATCH_FILES = (
    "HEAD",
    "index",
    "packed-refs",
    "FETCH_HEAD",
    "ORIG_HEAD",
    "MERGE_HEAD",
    "refs/stash",
)
_WATCH_DIRS = (
    "refs/heads",
    "refs/remotes",
    "refs/tags",
    "logs",
    "worktrees",
)


def resolve_git_dirs(repo_path: Path) -> tuple[Path, Path] | None:
    """The two directories holding *repo_path*'s git state, or None if it has none.

    In an ordinary clone `.git` is a directory and both are it. In a linked
    worktree — and in a submodule — `.git` is a *file* holding one `gitdir:`
    line, and treating it as a directory finds nothing at all.

    A worktree splits its state across the two: `HEAD`, `index` and `ORIG_HEAD`
    live in the per-worktree directory the file points at, while `refs/`,
    `packed-refs` and the object store stay behind in the common directory that
    directory's `commondir` file names. Watching only one of them is half a
    fix — the per-worktree directory alone misses every fetch and branch
    update, the common directory alone misses this worktree's own HEAD moving.

    A submodule points at a directory that is complete on its own and writes no
    `commondir`, so there the two come back equal.
    """

    def _absolute(raw: str, relative_to: Path) -> Path:
        # normpath rather than resolve: resolve() also expands symlinks, which
        # on macOS turns /tmp into /private/tmp and stops the watched paths
        # matching the ones a caller asked about.
        candidate = Path(raw)
        if candidate.is_absolute():
            return candidate
        return Path(os.path.normpath(relative_to / candidate))

    def _first_line(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError as e:
            logger.warning("RepoChangeDetector: could not read %s: %s", path, e)
            return ""

    dot_git = repo_path / ".git"
    if dot_git.is_dir():
        return dot_git, dot_git
    if not dot_git.is_file():
        return None

    pointer = _first_line(dot_git)
    prefix = "gitdir:"
    if not pointer.startswith(prefix):
        logger.warning("RepoChangeDetector: %s is not a gitdir pointer", dot_git)
        return None

    git_dir = _absolute(pointer[len(prefix) :].strip(), repo_path)
    if not git_dir.is_dir():
        logger.warning("RepoChangeDetector: %s points at missing %s", dot_git, git_dir)
        return None

    common_file = git_dir / "commondir"
    if not common_file.is_file():
        # A submodule: its git directory carries its own refs and objects.
        return git_dir, git_dir
    raw_common = _first_line(common_file)
    if not raw_common:
        return git_dir, git_dir
    return git_dir, _absolute(raw_common, git_dir)


class RepoChangeDetector(QObject):
    """Watch the repo's git directories for external changes, and GitCrisp's
    own focus state.
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
        *,
        debounce_ms: int = _DEBOUNCE_MS,
        suppress_ms: int = _SELF_RELOAD_SUPPRESS_MS,
    ) -> None:
        """The two windows are arguments so a test can pick unambiguous ones.

        Left as constants, a test can only wait a fixed number of milliseconds
        and hope the machine keeps up — which turns "events coalesce" into a
        race against the scheduler.
        """
        super().__init__(parent)
        self._repo_path = Path(repo_path)
        self._on_reload = on_reload
        self._suppress_ms = suppress_ms

        # Debouncer — single-shot timer, restarted on each event.
        self._debouncer = QTimer(self)
        self._debouncer.setSingleShot(True)
        self._debouncer.setInterval(debounce_ms)
        self._debouncer.timeout.connect(self._fire_reload)

        # Git-state watcher.
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._schedule_reload)
        self._watcher.directoryChanged.connect(self._schedule_reload)
        self._add_git_watch_paths()

        # Focus watcher.
        app = QGuiApplication.instance()
        # Whether the connection was made is tracked rather than rediscovered:
        # disconnecting something that is not connected makes Qt warn without
        # raising, so a try/except around it catches nothing and the warning
        # prints anyway.
        self._app_state_connected = False
        if app is not None:
            app.applicationStateChanged.connect(self._on_app_state_changed)
            self._app_state_connected = True

        self._suppress_until_ms: float = 0.0

    # ── Public API ──────────────────────────────────────────────────────

    def stop(self) -> None:
        """Disconnect and release watches. Idempotent."""
        app = QGuiApplication.instance()
        if app is not None and self._app_state_connected:
            app.applicationStateChanged.disconnect(self._on_app_state_changed)
            self._app_state_connected = False
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
        self._suppress_until_ms = monotonic() * 1000.0 + self._suppress_ms

    # ── Watch-set setup ─────────────────────────────────────────────────

    def _add_git_watch_paths(self) -> None:
        """Add every file and directory holding git state that indicates a
        change. Missing paths are silently skipped."""
        resolved = resolve_git_dirs(self._repo_path)
        if resolved is None:
            logger.warning("RepoChangeDetector: no git directory at %s", self._repo_path)
            return
        git_dir, common_dir = resolved

        # Each name is looked for under both roots rather than assigned to one:
        # which of the two holds a given name is git's business and it varies by
        # git version, so asking the filesystem is steadier than encoding the
        # split here. In an ordinary clone the two are equal and this is one
        # root, so nothing is looked up or watched twice.
        roots = [git_dir] if git_dir == common_dir else [git_dir, common_dir]

        for root in roots:
            self._watch(root, root.is_dir, "dir")
        for name in _WATCH_FILES:
            for root in roots:
                path = root / name
                self._watch(path, path.is_file, "file")
        for name in _WATCH_DIRS:
            for root in roots:
                path = root / name
                self._watch(path, path.is_dir, "dir")

    def _watch(self, path: Path, exists: Callable[[], bool], kind: str) -> None:
        if exists() and not self._watcher.addPath(str(path)):
            logger.warning("RepoChangeDetector: could not watch %s %s", kind, path)

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
