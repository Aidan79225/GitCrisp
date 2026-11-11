"""The scenario behind test_repo_change_detector_stop.py, run in a process of its own.

Qt's Windows file-watcher thread can log "QFileSystemWatcher: FindNextChangeNotification failed"
when a directory it watches is deleted, and it logs while it holds the lock that addPath and
removePaths take; RepoChangeDetector._release_watches says what that has to do with the GIL.

The handler below stands in for the app's Python message handler. It is entered on the watcher's
thread, which is then inside the log call with the lock held, and it stays there until a helper
thread says it may go. The helper is a Python thread, so it runs only while the main thread has let
go of the GIL: a stop() that waits for the lock with the GIL held never returns, and one that does
not returns once the helper has run.

    uv run python -m tests.presentation.services.scenario_stop_while_the_watcher_thread_logs DIR

Run it from the repository root. DIR is where to build the fake repository. Use a new folder for
every run: the scenario raises FileExistsError when DIR already holds the .git of an earlier run.
Prints "holding" once the thread is held inside the log call and stop() is about to be called, then
"stopped" and exits 0 when stop() returned. When Qt never logged there was nothing to hold the
thread with: it prints "Qt did not log" and exits 2, and the test counts that as a failure too,
because a Qt that stopped logging would otherwise leave stop() untested without a word.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from PySide6.QtCore import qInstallMessageHandler
from PySide6.QtGui import QGuiApplication

from git_gui.presentation.services.repo_change_detector import RepoChangeDetector

# How long the helper keeps the thread inside the log call, counted from just before stop() is
# called. stop() has to reach the lock inside that time, or a stop() that waits for it with the GIL
# would find the thread gone and pass; a second leaves room for a machine busy with other work.
_HELD_FOR_S = 1.0
# Qt logs within milliseconds of the directory going; this is only the wait for a slow machine.
_LOG_WAIT_S = 10


def main(directory: Path) -> int:
    app = QGuiApplication([])  # the detector needs an application, and it has to outlive it
    git_dir = directory / ".git"
    for name in ("refs/heads", "refs/tags", "logs", "worktrees"):
        (git_dir / name).mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

    log_call_entered = threading.Event()
    may_return = threading.Event()

    def message_handler(_mode, _context, message: str) -> None:
        if "FindNextChangeNotification" in message:
            log_call_entered.set()
            may_return.wait()

    qInstallMessageHandler(message_handler)
    detector = RepoChangeDetector(str(directory), on_reload=lambda: None)

    # The last thing git does when the last linked worktree goes. Done bare like this it makes Qt log
    # every time; git's own removal logs only some of the time, so the scenario does not use git.
    (git_dir / "worktrees").rmdir()
    if not log_call_entered.wait(_LOG_WAIT_S):
        print("Qt did not log", flush=True)
        return 2

    threading.Timer(_HELD_FOR_S, may_return.set).start()
    print("holding", flush=True)
    detector.stop()
    print("stopped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
