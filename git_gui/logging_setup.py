"""Minimal file-logging setup for GitCrisp.

A single rotating file handler on the root logger, writing to
``~/.gitcrisp/logs/gitcrisp.log``. Called once from ``main.main()``
before the ``QApplication`` starts.

Idempotent — calling ``setup_logging()`` multiple times is safe and
will not install duplicate handlers.
"""
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
