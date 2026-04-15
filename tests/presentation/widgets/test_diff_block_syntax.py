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


def _bg_color_at(editor: QPlainTextEdit, line_index: int, col: int) -> str:
    """Return the QTextCharFormat background color at (line_index, col) as hex."""
    from PySide6.QtGui import QColor
    block = editor.document().findBlockByNumber(line_index)
    cursor = editor.textCursor()
    cursor.setPosition(block.position() + col + 1)
    fmt = cursor.charFormat()
    bg = fmt.background().color()
    return bg.name(QColor.HexArgb)


def test_paired_minus_plus_marks_changed_word_with_overlay(qtbot):
    """A -/+ pair where only one token differs: that token gets the word overlay."""
    hunk = Hunk(
        header="@@ -1,2 +1,2 @@",
        lines=[
            ("-", "x = 1\n"),
            ("+", "x = 2\n"),
        ],
    )
    editor = _editor_for_hunk(qtbot, hunk, "x.py")

    # Prefix on - line: "   1       " (4+7 = 11 chars). Content "x = 1" → '1' at col 11+4 = 15.
    minus_bg = _bg_color_at(editor, 0, 15)
    plus_bg = _bg_color_at(editor, 1, 15)

    # We don't compare colors strictly (they merge with line bg); we just assert
    # the overlay differs from the unchanged-region background.
    minus_unchanged_bg = _bg_color_at(editor, 0, 11)  # the 'x'
    plus_unchanged_bg = _bg_color_at(editor, 1, 11)
    assert minus_bg != minus_unchanged_bg
    assert plus_bg != plus_unchanged_bg


def test_pure_addition_hunk_has_no_word_overlay(qtbot):
    """A hunk with only + lines (no adjacent -) gets no word-level overlay."""
    hunk = Hunk(
        header="@@ -1,0 +1,2 @@",
        lines=[
            ("+", "x = 1\n"),
            ("+", "y = 2\n"),
        ],
    )
    editor = _editor_for_hunk(qtbot, hunk, "x.py")
    # Without a paired - line, the '1' at col 15 should share the same background
    # as the unchanged region (e.g., the 'x' at col 11) on the same line.
    bg_at_change = _bg_color_at(editor, 0, 15)  # the '1'
    bg_at_unchanged = _bg_color_at(editor, 0, 11)  # the 'x'
    assert bg_at_change == bg_at_unchanged


def test_non_adjacent_minus_plus_not_paired(qtbot):
    """- followed by context, then +: not adjacent, no word-level pairing."""
    hunk = Hunk(
        header="@@ -1,3 +1,3 @@",
        lines=[
            ("-", "x = 1\n"),
            (" ", "noop\n"),
            ("+", "x = 2\n"),
        ],
    )
    editor = _editor_for_hunk(qtbot, hunk, "x.py")
    # The '1' on the - line and '2' on the + line should NOT carry the word overlay.
    minus_bg_at_change = _bg_color_at(editor, 0, 15)  # '1'
    minus_bg_at_unchanged = _bg_color_at(editor, 0, 11)  # 'x'
    # Without pairing, all chars on the - line share the same line background.
    assert minus_bg_at_change == minus_bg_at_unchanged


def test_word_overlay_preserves_syntax_foreground(qtbot):
    """A changed token that is also a Pygments Name.Function keeps its syntax fg
    while gaining the word-overlay background — verifies mergeCharFormat layering."""
    hunk = Hunk(
        header="@@ -1,2 +1,2 @@",
        lines=[
            ("-", "def foo():\n"),
            ("+", "def bar():\n"),
        ],
    )
    editor = _editor_for_hunk(qtbot, hunk, "x.py")
    syntax = make_syntax_formats()
    keyword_fg = syntax.keyword.foreground().color().name()
    function_fg = syntax.function.foreground().color().name()

    # 'def' at col 11 on the - line — keyword fg, no overlay (unchanged).
    fmt_def = _format_at(editor, 0, 11)
    assert fmt_def.foreground().color().name() == keyword_fg
    # 'foo' at col 15 on the - line — function fg AND removed_word_overlay bg.
    fmt_foo = _format_at(editor, 0, 15)
    assert fmt_foo.foreground().color().name() == function_fg
    # The overlay sets a non-default background — different from the 'def' position.
    assert _bg_color_at(editor, 0, 15) != _bg_color_at(editor, 0, 11)

    # 'def' on the + line — keyword fg, no overlay.
    fmt_def_plus = _format_at(editor, 1, 11)
    assert fmt_def_plus.foreground().color().name() == keyword_fg
    # 'bar' at col 15 on the + line — function fg AND added_word_overlay bg.
    fmt_bar = _format_at(editor, 1, 15)
    assert fmt_bar.foreground().color().name() == function_fg
    assert _bg_color_at(editor, 1, 15) != _bg_color_at(editor, 1, 11)
