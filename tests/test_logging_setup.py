"""Tests for the logging_setup module."""

from __future__ import annotations

import faulthandler
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
    original_fault_enabled = faulthandler.is_enabled()
    yield
    # Remove any handlers added during the test
    for handler in list(root.handlers):
        if handler not in original_handlers:
            handler.close()
            root.removeHandler(handler)
    root.setLevel(original_level)
    sys.excepthook = original_sys_hook
    threading.excepthook = original_thread_hook
    # Disable faulthandler if the test enabled it; close the fp so the next
    # test gets a fresh open() against its own monkey-patched _FAULT_FILE.
    if logging_setup._fault_fp is not None:
        faulthandler.disable()
        logging_setup._fault_fp.close()
        logging_setup._fault_fp = None
    if original_fault_enabled and not faulthandler.is_enabled():
        faulthandler.enable()


def _point_log_dir_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect logging_setup's log file into tmp_path for isolation."""
    log_dir = tmp_path / "logs"
    log_file = log_dir / "gitcrisp.log"
    fault_file = log_dir / "faulthandler.log"
    monkeypatch.setattr(logging_setup, "_LOG_DIR", log_dir)
    monkeypatch.setattr(logging_setup, "_LOG_FILE", log_file)
    monkeypatch.setattr(logging_setup, "_FAULT_FILE", fault_file)
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
        h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
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


def test_setup_logging_enables_faulthandler(tmp_path, monkeypatch):
    _point_log_dir_at(tmp_path, monkeypatch)

    logging_setup.setup_logging()

    assert faulthandler.is_enabled()
    assert logging_setup._fault_fp is not None
    assert (tmp_path / "logs" / "faulthandler.log").exists()


def test_setup_logging_faulthandler_idempotent(tmp_path, monkeypatch):
    _point_log_dir_at(tmp_path, monkeypatch)

    logging_setup.setup_logging()
    first_fp = logging_setup._fault_fp
    logging_setup.setup_logging()
    logging_setup.setup_logging()

    # Same fp object across calls — file is opened exactly once.
    assert logging_setup._fault_fp is first_fp
    assert faulthandler.is_enabled()


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


def test_records_past_the_size_limit_survive_another_process_holding_the_log(tmp_path, monkeypatch):
    """A second GitCrisp keeps the log open, and Windows will not rename an
    open file, so every rollover fails; the records must still reach disk."""
    log_file = _point_log_dir_at(tmp_path, monkeypatch)
    monkeypatch.setattr(logging_setup, "_MAX_BYTES", 2000)
    monkeypatch.setattr(logging, "raiseExceptions", False)
    logging_setup.setup_logging()
    logger = logging.getLogger("test.held_log")

    with open(log_file, "a", encoding="utf-8"):
        for i in range(100):
            logger.warning("record-%03d", i)
        for handler in logging.getLogger().handlers:
            handler.flush()

    written = "".join(
        path.read_text(encoding="utf-8") for path in log_file.parent.glob("gitcrisp.log*")
    )
    assert [i for i in range(100) if f"record-{i:03d}" not in written] == []


def test_a_rollover_that_cannot_move_the_log_keeps_every_backup(tmp_path, monkeypatch):
    """While a second GitCrisp holds the log, no rollover can finish; the
    backups of earlier sessions must not be shifted away trying."""
    log_file = _point_log_dir_at(tmp_path, monkeypatch)
    monkeypatch.setattr(logging_setup, "_MAX_BYTES", 2000)
    monkeypatch.setattr(logging, "raiseExceptions", False)
    log_file.parent.mkdir(parents=True)
    for n in (1, 2, 3):
        Path(f"{log_file}.{n}").write_text(f"BACKUP-{n}", encoding="utf-8")
    log_file.write_text("x" * 3000, encoding="utf-8")
    logging_setup.setup_logging()
    handler = next(
        h
        for h in logging.getLogger().handlers
        if isinstance(h, logging_setup._SharedRotatingFileHandler)
    )

    def held_by_another_process(source: str, dest: str) -> None:
        raise PermissionError(32, "The file is in use by another process", source)

    monkeypatch.setattr(handler, "rotate", held_by_another_process)
    for i in range(5):
        logging.getLogger("test.held_log").warning("record-%d", i)

    backups = {
        n: Path(f"{log_file}.{n}").read_text(encoding="utf-8")
        for n in (1, 2, 3)
        if Path(f"{log_file}.{n}").exists()
    }
    assert backups == {1: "BACKUP-1", 2: "BACKUP-2", 3: "BACKUP-3"}


def test_a_rollover_moves_the_log_to_the_first_backup_and_drops_the_oldest(tmp_path, monkeypatch):
    log_file = _point_log_dir_at(tmp_path, monkeypatch)
    monkeypatch.setattr(logging_setup, "_MAX_BYTES", 2000)
    log_file.parent.mkdir(parents=True)
    for n in (1, 2, 3):
        Path(f"{log_file}.{n}").write_text(f"BACKUP-{n}", encoding="utf-8")
    log_file.write_text("FULL" + "x" * 3000, encoding="utf-8")
    logging_setup.setup_logging()

    logging.getLogger("test.rollover").warning("first record of the new log")

    def backup(n: int) -> str:
        return Path(f"{log_file}.{n}").read_text(encoding="utf-8")

    assert [backup(1)[:4], backup(2), backup(3)] == ["FULL", "BACKUP-1", "BACKUP-2"]
    assert not Path(f"{log_file}.4").exists()
    assert not Path(f"{log_file}.rolling").exists()
