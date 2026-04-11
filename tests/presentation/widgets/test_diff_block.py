"""Tests for chunked rendering of large hunks in diff_block."""
from __future__ import annotations
from PySide6.QtGui import QTextDocument, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

from git_gui.domain.entities import Hunk
from git_gui.presentation.widgets.diff_block import (
    render_hunk_content_lines, make_diff_formats,
)


def _make_cursor(qtbot):
    edit = QPlainTextEdit()
    qtbot.addWidget(edit)
    return edit.textCursor(), edit


def test_small_hunk_renders_immediately(qtbot):
    """A 50-line hunk is fully rendered in the initial call."""
    lines = [(" ", f"line {i}\n") for i in range(50)]
    hunk = Hunk(header="@@ -1,50 +1,50 @@", lines=lines)
    cursor, edit = _make_cursor(qtbot)
    formats = make_diff_formats()

    render_hunk_content_lines(cursor, hunk, formats)

    assert edit.document().blockCount() >= 50


def test_large_hunk_renders_first_chunk_immediately(qtbot):
    """A 500-line hunk has at least 100 lines rendered immediately."""
    lines = [(" ", f"line {i}\n") for i in range(500)]
    hunk = Hunk(header="@@ -1,500 +1,500 @@", lines=lines)
    cursor, edit = _make_cursor(qtbot)
    formats = make_diff_formats()

    render_hunk_content_lines(cursor, hunk, formats)

    # Immediately after the call, first chunk (100 lines) should be rendered
    assert edit.document().blockCount() >= 100


def test_large_hunk_completes_rendering_after_event_loop(qtbot):
    """A 500-line hunk completes rendering after the event loop processes QTimer callbacks."""
    lines = [(" ", f"line {i}\n") for i in range(500)]
    hunk = Hunk(header="@@ -1,500 +1,500 @@", lines=lines)
    cursor, edit = _make_cursor(qtbot)
    formats = make_diff_formats()

    render_hunk_content_lines(cursor, hunk, formats)

    # Wait for QTimer.singleShot callbacks to fire
    qtbot.wait(200)
    assert edit.document().blockCount() >= 500
