"""Tests for the logging_setup module."""
from __future__ import annotations
import logging
import logging.handlers
from pathlib import Path

import pytest

from git_gui import logging_setup


@pytest.fixture(autouse=True)
def _reset_root_logger():
    """Snapshot and restore the root logger around each test.

    setup_logging() mutates global state, so we need to clean up afterwards
    to avoid leaking handlers into other tests.
    """
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    yield
    # Remove any handlers added during the test
    for handler in list(root.handlers):
        if handler not in original_handlers:
            handler.close()
            root.removeHandler(handler)
    root.setLevel(original_level)


def _point_log_dir_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect logging_setup's log file into tmp_path for isolation."""
    log_dir = tmp_path / "logs"
    log_file = log_dir / "gitcrisp.log"
    monkeypatch.setattr(logging_setup, "_LOG_DIR", log_dir)
    monkeypatch.setattr(logging_setup, "_LOG_FILE", log_file)
    return log_file


def test_setup_logging_creates_file(tmp_path, monkeypatch):
    log_file = _point_log_dir_at(tmp_path, monkeypatch)

    logging_setup.setup_logging()

    logger = logging.getLogger("test.creates_file")
    logger.warning("hello from test_setup_logging_creates_file")
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "hello from test_setup_logging_creates_file" in content
    assert "WARNING" in content
    assert "test.creates_file" in content


def test_setup_logging_is_idempotent(tmp_path, monkeypatch):
    _point_log_dir_at(tmp_path, monkeypatch)

    logging_setup.setup_logging()
    logging_setup.setup_logging()
    logging_setup.setup_logging()

    root = logging.getLogger()
    rotating_handlers = [
        h for h in root.handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(rotating_handlers) == 1


def test_setup_logging_ignores_debug_by_default(tmp_path, monkeypatch):
    log_file = _point_log_dir_at(tmp_path, monkeypatch)

    logging_setup.setup_logging()

    logger = logging.getLogger("test.debug_filter")
    logger.debug("debug-should-not-appear")
    logger.warning("warning-should-appear")
    for handler in logging.getLogger().handlers:
        handler.flush()

    content = log_file.read_text(encoding="utf-8")
    assert "debug-should-not-appear" not in content
    assert "warning-should-appear" in content
