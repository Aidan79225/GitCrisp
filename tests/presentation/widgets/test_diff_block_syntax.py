from __future__ import annotations
import pytest
from PySide6.QtWidgets import QPlainTextEdit

from git_gui.domain.entities import Hunk
from git_gui.presentation.widgets.diff_block import (
    make_diff_formats, make_syntax_formats, render_hunk_content_lines,
)


def _editor_for_hunk(qtbot, hunk: Hunk, filename: str) -> QPlainTextEdit:
    editor = QPlainTextEdit()
    qtbot.addWidget(editor)
    diff_formats = make_diff_formats()
    syntax_formats = make_syntax_formats()
    cursor = editor.textCursor()
    render_hunk_content_lines(
        cursor, hunk, diff_formats,
        syntax_formats=syntax_formats, filename=filename,
    )
    return editor


def _format_at(editor: QPlainTextEdit, line_index: int, col: int):
    """Return the QTextCharFormat at (line_index, col) in the editor."""
    block = editor.document().findBlockByNumber(line_index)
    text = block.text()
    assert col < len(text), f"col {col} out of range for line {text!r}"
    cursor = editor.textCursor()
    cursor.setPosition(block.position() + col + 1)  # +1 to read the char before
    return cursor.charFormat()


def test_python_keyword_gets_syntax_color(qtbot):
    hunk = Hunk(
        header="@@ -1,1 +1,1 @@",
        lines=[(" ", "def foo():\n")],
    )
    editor = _editor_for_hunk(qtbot, hunk, "x.py")
    # The line layout is "<prefix>def foo():" — prefix length is 11 chars
    # ("   1    1  " = 4+1+4+2 = 11). The 'd' of "def" sits at col 11.
    # Read the format at the position of 'd'.
    fmt = _format_at(editor, 0, 11)
    fg = fmt.foreground().color().name()
    syntax_kw = make_syntax_formats().keyword.foreground().color().name()
    assert fg == syntax_kw


def test_long_line_skips_syntax_pass(qtbot):
    long_line = "x = " + "a" * 2100 + "\n"  # > 2000 chars total
    hunk = Hunk(
        header="@@ -1,1 +1,1 @@",
        lines=[(" ", long_line)],
    )
    editor = _editor_for_hunk(qtbot, hunk, "x.py")
    # The 'x' at col 11 should NOT have any syntax color applied —
    # it should keep the default fg from DiffFormats.fmt_default.
    fmt = _format_at(editor, 0, 11)
    fg = fmt.foreground().color().name()
    diff_default = make_diff_formats().fmt_default.foreground().color().name()
    assert fg == diff_default


def test_unknown_extension_no_syntax_format(qtbot):
    hunk = Hunk(
        header="@@ -1,1 +1,1 @@",
        lines=[(" ", "def foo():\n")],
    )
    editor = _editor_for_hunk(qtbot, hunk, "x.unknownext")
    # 'd' at col 11 should NOT be colored as a keyword.
    fmt = _format_at(editor, 0, 11)
    fg = fmt.foreground().color().name()
    syntax_kw = make_syntax_formats().keyword.foreground().color().name()
    assert fg != syntax_kw
