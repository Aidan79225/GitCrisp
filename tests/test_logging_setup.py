"""Tests for the logging_setup module."""
from __future__ import annotations
import logging
import logging.handlers
import sys
import threading
from pathlib import Path

import pytest

from git_gui import logging_setup


@pytest.fixture(autouse=True)
def _reset_root_logger():
    """Snapshot and restore the root logger + excepthooks around each test.

    setup_logging() mutates global state, so we need to clean up afterwards
    to avoid leaking handlers or hooks into other tests.
    """
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    original_sys_hook = sys.excepthook
    original_thread_hook = threading.excepthook
    yield
    # Remove any handlers added during the test
    for handler in list(root.handlers):
        if handler not in original_handlers:
            handler.close()
            root.removeHandler(handler)
    root.setLevel(original_level)
    sys.excepthook = original_sys_hook
    threading.excepthook = original_thread_hook


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


def test_setup_logging_installs_sys_excepthook(tmp_path, monkeypatch):
    _point_log_dir_at(tmp_path, monkeypatch)

    logging_setup.setup_logging()

    assert sys.excepthook is logging_setup._log_uncaught


def test_setup_logging_installs_threading_excepthook(tmp_path, monkeypatch):
    _point_log_dir_at(tmp_path, monkeypatch)

    logging_setup.setup_logging()

    assert threading.excepthook is logging_setup._log_uncaught_thread


def test_uncaught_exception_is_logged(tmp_path, monkeypatch):
    log_file = _point_log_dir_at(tmp_path, monkeypatch)

    logging_setup.setup_logging()

    # Simulate an uncaught exception by invoking the hook directly
    try:
        raise ValueError("simulated boom")
    except ValueError:
        exc_type, exc_value, exc_traceback = sys.exc_info()
    logging_setup._log_uncaught(exc_type, exc_value, exc_traceback)

    for handler in logging.getLogger().handlers:
        handler.flush()
    content = log_file.read_text(encoding="utf-8")
    assert "Uncaught exception" in content
    assert "CRITICAL" in content
    assert "ValueError" in content
    assert "simulated boom" in content
    # Full traceback should be present
    assert "Traceback" in content


def test_keyboard_interrupt_is_not_logged(tmp_path, monkeypatch, capsys):
    log_file = _point_log_dir_at(tmp_path, monkeypatch)

    logging_setup.setup_logging()

    try:
        raise KeyboardInterrupt()
    except KeyboardInterrupt:
        exc_type, exc_value, exc_traceback = sys.exc_info()
    logging_setup._log_uncaught(exc_type, exc_value, exc_traceback)

    for handler in logging.getLogger().handlers:
        handler.flush()
    content = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
    assert "KeyboardInterrupt" not in content


def test_thread_uncaught_exception_is_logged(tmp_path, monkeypatch):
    log_file = _point_log_dir_at(tmp_path, monkeypatch)

    logging_setup.setup_logging()

    def _boom():
        raise RuntimeError("thread boom")

    t = threading.Thread(target=_boom, name="test-worker")
    t.start()
    t.join()

    for handler in logging.getLogger().handlers:
        handler.flush()
    content = log_file.read_text(encoding="utf-8")
    assert "Uncaught exception in thread" in content
    assert "test-worker" in content
    assert "RuntimeError" in content
    assert "thread boom" in content
