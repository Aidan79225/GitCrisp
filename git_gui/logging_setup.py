"""Minimal file-logging setup for GitCrisp.

A single rotating file handler on the root logger, writing to
``~/.gitcrisp/logs/gitcrisp.log``. Called once from ``main.main()``
before the ``QApplication`` starts.

Also installs global exception hooks so any uncaught exception (main
thread or background thread) is logged at CRITICAL level with a full
traceback before the interpreter exits or the thread dies.

Native crashes (segfaults, access violations) are captured by
``faulthandler`` into ``~/.gitcrisp/logs/faulthandler.log`` with the
Python stacks of every thread at the moment of the fault.

Idempotent — calling ``setup_logging()`` multiple times is safe and
will not install duplicate handlers or hooks.
"""

from __future__ import annotations

import faulthandler
import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path
from typing import IO

_LOG_DIR = Path.home() / ".gitcrisp" / "logs"
_LOG_FILE = _LOG_DIR / "gitcrisp.log"
_FAULT_FILE = _LOG_DIR / "faulthandler.log"
_MAX_BYTES = 1_000_000  # 1 MB per file
_BACKUP_COUNT = 3  # keep gitcrisp.log.1 .. .3

_uncaught_logger = logging.getLogger("gitcrisp.uncaught")
_fault_fp: IO[str] | None = None


class _SharedRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """A rotating handler that keeps appending when the log cannot be rotated.

    Every running GitCrisp holds the same log open, and Windows will not
    rename a file another process has open. The stock handler then drops the
    record, and every record after it, for as long as the other one runs; a
    log that outgrows its limit loses less than one that goes silent.

    The log is moved aside before the backups are touched. The stock handler
    shifts and deletes them first and fails only at the last rename, so every
    record past the limit would push the logs of earlier sessions out.
    """

    def doRollover(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None
        aside = f"{self.baseFilename}.rolling"
        if self._moved(self.baseFilename, aside):
            self._shift_backups()
            self.rotate(aside, self._backup_name(1))
        if not self.delay:
            self.stream = self._open()

    def _moved(self, source: str, dest: str) -> bool:
        """Move *source* to *dest*, or say it is held open and cannot move."""
        try:
            if os.path.exists(dest):
                os.remove(dest)  # left by a rollover that a crash cut short
            self.rotate(source, dest)
        except OSError:
            return False
        return True

    def _shift_backups(self) -> None:
        """Move each backup one place down, dropping the oldest."""
        for n in range(self.backupCount - 1, 0, -1):
            if os.path.exists(self._backup_name(n)):
                os.replace(self._backup_name(n), self._backup_name(n + 1))
        if os.path.exists(self._backup_name(1)):
            os.remove(self._backup_name(1))

    def _backup_name(self, n: int) -> str:
        return self.rotation_filename(f"{self.baseFilename}.{n}")


def _log_uncaught(exc_type, exc_value, exc_traceback) -> None:
    """Log uncaught main-thread exceptions, then delegate to the default hook.

    KeyboardInterrupt is passed through unchanged so Ctrl+C still exits cleanly.
    """
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    _uncaught_logger.critical(
        "Uncaught exception",
        exc_info=(exc_type, exc_value, exc_traceback),
    )
    sys.__excepthook__(exc_type, exc_value, exc_traceback)


def _log_uncaught_thread(args) -> None:
    """Log uncaught exceptions raised inside background threads."""
    if issubclass(args.exc_type, SystemExit):
        return
    thread_name = args.thread.name if args.thread else "<unknown>"
    _uncaught_logger.critical(
        "Uncaught exception in thread %r",
        thread_name,
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


def setup_logging() -> None:
    """Configure the root logger with a single rotating file handler.

    Also installs ``sys.excepthook`` and ``threading.excepthook`` so
    uncaught exceptions are logged with full tracebacks.

    Idempotent — calling it twice does not install duplicate handlers
    or hooks.
    """
    root = logging.getLogger()
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = _SharedRotatingFileHandler(
            _LOG_FILE,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.setLevel(logging.WARNING)
        root.addHandler(handler)

    # Install excepthooks (idempotent — only replace if not already ours)
    if sys.excepthook is not _log_uncaught:
        sys.excepthook = _log_uncaught
    if threading.excepthook is not _log_uncaught_thread:
        threading.excepthook = _log_uncaught_thread

    # Enable faulthandler so native crashes (segfaults, EXCEPTION_ACCESS_VIOLATION
    # on Windows) dump every thread's Python stack to faulthandler.log before
    # the interpreter dies. Idempotent — only opens the file once per process.
    global _fault_fp
    if _fault_fp is None:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        _fault_fp = open(_FAULT_FILE, "a", buffering=1, encoding="utf-8")
        faulthandler.enable(file=_fault_fp, all_threads=True)
