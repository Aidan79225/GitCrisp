"""Minimal file-logging setup for GitCrisp.

A single rotating file handler on the root logger, writing to
``~/.gitcrisp/logs/gitcrisp.log``. Called once from ``main.main()``
before the ``QApplication`` starts.

Also installs global exception hooks so any uncaught exception (main
thread or background thread) is logged at CRITICAL level with a full
traceback before the interpreter exits or the thread dies.

Idempotent — calling ``setup_logging()`` multiple times is safe and
will not install duplicate handlers or hooks.
"""
from __future__ import annotations
import logging
import logging.handlers
import sys
import threading
from pathlib import Path

_LOG_DIR = Path.home() / ".gitcrisp" / "logs"
_LOG_FILE = _LOG_DIR / "gitcrisp.log"
_MAX_BYTES = 1_000_000  # 1 MB per file
_BACKUP_COUNT = 3       # keep gitcrisp.log.1 .. .3

_uncaught_logger = logging.getLogger("gitcrisp.uncaught")


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

    # Install excepthooks (idempotent — only replace if not already ours)
    if sys.excepthook is not _log_uncaught:
        sys.excepthook = _log_uncaught
    if threading.excepthook is not _log_uncaught_thread:
        threading.excepthook = _log_uncaught_thread
