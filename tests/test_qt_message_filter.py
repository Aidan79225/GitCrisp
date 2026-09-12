import logging
import sys

from PySide6.QtCore import QtMsgType

from main import _SUPPRESSED_FRAGMENTS, _qt_message_filter


class TestQtMessageFilter:
    def test_suppresses_monitor_interface_warning(self, capsys, caplog):
        with caplog.at_level(logging.DEBUG):
            _qt_message_filter(
                QtMsgType.QtWarningMsg,
                None,
                'Unable to open monitor interface to \\\\.\\DISPLAY1: "Unknown error 0xe0000225."',
            )
        assert capsys.readouterr().err == ""
        assert "Suppressed Qt warning" in caplog.text

    def test_suppresses_device_pixel_ratio_warning(self, capsys, caplog):
        with caplog.at_level(logging.DEBUG):
            _qt_message_filter(
                QtMsgType.QtWarningMsg,
                None,
                "The cached device pixel ratio value was stale on window expose. "
                "Please file a QTBUG which explains how to reproduce.",
            )
        assert capsys.readouterr().err == ""
        assert "Suppressed Qt warning" in caplog.text

    def test_passes_through_unrelated_warning(self, capsys):
        _qt_message_filter(
            QtMsgType.QtWarningMsg,
            None,
            "Some other Qt warning",
        )
        captured = capsys.readouterr().err
        assert "Some other Qt warning" in captured

    def test_passes_through_debug_message(self, capsys):
        _qt_message_filter(
            QtMsgType.QtDebugMsg,
            None,
            "debug info",
        )
        captured = capsys.readouterr().err
        assert "debug info" in captured
        assert "QtDebugMsg" in captured

    def test_suppressed_fragments_tuple_is_not_empty(self):
        assert len(_SUPPRESSED_FRAGMENTS) >= 2


class TestQtMessageFilterWithoutStderr:
    """A windowed build — pythonw, or PyInstaller --windowed — has no stderr.

    Writing to it unguarded raises inside Qt's message handler, and that
    exception surfaces in whatever code happened to trigger the message. A
    missing-icon warning while building a hunk block is how that stopped the
    working-tree diff rendering at all.
    """

    def test_does_not_raise_when_stderr_is_none(self, monkeypatch):
        monkeypatch.setattr(sys, "stderr", None)

        _qt_message_filter(QtMsgType.QtWarningMsg, None, "Cannot open file 'arts/ic_close.svg'")

    def test_message_still_reaches_the_log_without_stderr(self, monkeypatch, caplog):
        monkeypatch.setattr(sys, "stderr", None)

        with caplog.at_level(logging.WARNING):
            _qt_message_filter(QtMsgType.QtWarningMsg, None, "Some other Qt warning")

        assert "Some other Qt warning" in caplog.text
