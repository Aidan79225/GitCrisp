"""git's "\\ No newline at end of file" note in both diff views.

libgit2 sends the note as a line of its own (origin '>', '<' or '='), placed
right after the line it is about, with its text wrapped in newlines. It is not
a line of either file: counting it numbered every later line one too high,
split the change it sat in so the rewrite lost its word highlight, and its
embedded newlines made rows the hunk's height did not allow for.
"""

from __future__ import annotations

from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

from git_gui.domain.entities import Hunk, LineKind
from git_gui.presentation.widgets.diff_block import (
    add_hunk_widget,
    make_diff_formats,
    make_syntax_formats,
)
from git_gui.presentation.widgets.side_by_side import align_hunk
from git_gui.presentation.widgets.side_by_side_block import LEFT, RIGHT, render_side

NOTE = "\n\\ No newline at end of file\n"

# What libgit2 1.9 sends for "a = 1\nb = 2" -> "a = 1\nb = 3", neither ending
# in a newline: each note follows the line it is about.
LAST_LINE_REWRITTEN = Hunk(
    header="@@ -1,2 +1,2 @@",
    lines=[
        (LineKind.CONTEXT, "a = 1\n"),
        (LineKind.REMOVED, "b = 2"),
        (LineKind.ADDED_EOFNL, NOTE),
        (LineKind.ADDED, "b = 3"),
        (LineKind.REMOVED_EOFNL, NOTE),
    ],
)

# "a\nb\nold" -> "a\nb\nnew\nmore\n": only the old side lacked the newline.
NEWLINE_ADDED = Hunk(
    header="@@ -1,3 +1,4 @@",
    lines=[
        (LineKind.CONTEXT, "a\n"),
        (LineKind.CONTEXT, "b\n"),
        (LineKind.REMOVED, "old"),
        (LineKind.ADDED_EOFNL, NOTE),
        (LineKind.ADDED, "new\n"),
        (LineKind.ADDED, "more\n"),
    ],
)


def _unified(qtbot, hunk: Hunk) -> tuple[QWidget, QPlainTextEdit]:
    """The host comes back too: it owns the editor, so dropping it deletes both."""
    host = QWidget()
    qtbot.addWidget(host)
    add_hunk_widget(
        QVBoxLayout(host),
        hunk,
        make_diff_formats(),
        syntax_formats=make_syntax_formats(),
        filename="f.py",
    )
    host.show()
    qtbot.waitExposed(host)
    return host, host.findChild(QPlainTextEdit)


def _lines(editor: QPlainTextEdit) -> list[str]:
    return editor.toPlainText().split("\n")


# ── Unified ──────────────────────────────────────────────────────────────────


def test_unified_shows_the_note_unnumbered_and_does_not_count_it(qtbot):
    _host, editor = _unified(qtbot, LAST_LINE_REWRITTEN)

    assert _lines(editor)[:5] == [
        "   1    1  a = 1",
        "   2       b = 2",
        "           \\ No newline at end of file",
        "        2  b = 3",
        "           \\ No newline at end of file",
    ]


def test_unified_fits_every_row_of_a_hunk_with_notes(qtbot):
    _host, editor = _unified(qtbot, LAST_LINE_REWRITTEN)

    assert editor.document().blockCount() == len(LAST_LINE_REWRITTEN.lines) + 1
    assert editor.verticalScrollBar().maximum() <= 1


def test_unified_still_word_diffs_a_rewrite_with_a_note_inside_it(qtbot):
    _host, editor = _unified(qtbot, LAST_LINE_REWRITTEN)
    overlay = make_syntax_formats().added_word_overlay.background().color()

    added = editor.document().findBlockByNumber(3)
    cursor = editor.textCursor()
    cursor.setPosition(added.position() + len("        2  b = 3"))  # reads the '3'
    assert cursor.charFormat().background().color() == overlay


def test_unified_numbers_a_long_hunk_past_its_first_slice_without_the_note(qtbot):
    """Lines after the first hundred render later and recount the ones before."""
    hunk = Hunk(
        header="@@ -1,50 +1,60 @@",
        lines=[(LineKind.REMOVED, f"x{i}\n") for i in range(49)]
        + [(LineKind.REMOVED, "x49"), (LineKind.ADDED_EOFNL, NOTE)]
        + [(LineKind.ADDED, f"y{i}\n") for i in range(60)],
    )
    host = QWidget()
    qtbot.addWidget(host)
    add_hunk_widget(QVBoxLayout(host), hunk, make_diff_formats())
    editor = host.findChild(QPlainTextEdit)

    qtbot.waitUntil(lambda: editor.document().blockCount() == len(hunk.lines) + 1)
    assert _lines(editor)[len(hunk.lines) - 1] == "       60  y59"


# ── Side by side ─────────────────────────────────────────────────────────────


def _numbers(rows, side: int) -> list[int]:
    cells = [row[side] for row in rows if row[side] is not None]
    return [cell.number for cell in cells if cell.number is not None]


def test_side_by_side_numbers_each_side_as_its_file_does(qtbot):
    rows = align_hunk(NEWLINE_ADDED)

    assert _numbers(rows, LEFT) == [1, 2, 3]
    assert _numbers(rows, RIGHT) == [1, 2, 3, 4]


def test_side_by_side_keeps_the_rewrite_on_one_row(qtbot):
    rows = align_hunk(LAST_LINE_REWRITTEN)

    texts = [(left.text if left else None, right.text if right else None) for left, right in rows]
    assert ("b = 2", "b = 3") in texts


def test_side_by_side_puts_the_note_on_the_side_it_is_about(qtbot):
    rows = align_hunk(NEWLINE_ADDED)

    notes = [
        (side, row[side].text)
        for row in rows
        for side in (LEFT, RIGHT)
        if row[side] is not None and row[side].number is None
    ]
    assert notes == [(LEFT, "\\ No newline at end of file")]


def test_side_by_side_renders_one_line_per_row(qtbot):
    rows = align_hunk(NEWLINE_ADDED)

    for side in (LEFT, RIGHT):
        editor = QPlainTextEdit()
        qtbot.addWidget(editor)
        render_side(
            editor.textCursor(),
            rows,
            side,
            make_diff_formats(),
            syntax_formats=make_syntax_formats(),
            filename="f.txt",
        )
        assert editor.document().blockCount() == len(rows) + 1
