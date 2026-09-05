"""One hunk drawn as two panes.

The point of the view is that a change reads across rather than down, and that
only holds while the two sides stay level: same number of lines, same height,
the shorter side of a change filled in rather than closed up.
"""

from __future__ import annotations

from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

from git_gui.domain.entities import Hunk
from git_gui.presentation.widgets.diff_block import make_diff_formats, make_syntax_formats
from git_gui.presentation.widgets.side_by_side import align_hunk
from git_gui.presentation.widgets.side_by_side_block import (
    LEFT,
    RIGHT,
    add_side_by_side_hunk_widget,
    make_filler_format,
    render_side,
)

REPLACED = Hunk(
    header="@@ -10,3 +20,5 @@",
    lines=[
        (" ", "context\n"),
        ("-", "old one\n"),
        ("-", "old two\n"),
        ("+", "new one\n"),
        ("+", "new two\n"),
        ("+", "new three\n"),
    ],
)


def _rendered(qtbot, hunk: Hunk, side: int, *, filename: str | None = None) -> QPlainTextEdit:
    editor = QPlainTextEdit()
    qtbot.addWidget(editor)
    cursor = editor.textCursor()
    render_side(
        cursor,
        align_hunk(hunk),
        side,
        make_diff_formats(),
        syntax_formats=make_syntax_formats() if filename else None,
        filename=filename,
    )
    return editor


def _lines(editor: QPlainTextEdit) -> list[str]:
    text = editor.toPlainText()
    return text.split("\n")[:-1] if text.endswith("\n") else text.split("\n")


def _pane(qtbot, hunk: Hunk, **kwargs) -> tuple[QWidget, list[QPlainTextEdit]]:
    host = QWidget()
    qtbot.addWidget(host)
    layout = QVBoxLayout(host)
    add_side_by_side_hunk_widget(layout, hunk, make_diff_formats(), **kwargs)
    return host, host.findChildren(QPlainTextEdit)


def _block_format(editor: QPlainTextEdit, line: int):
    return editor.document().findBlockByNumber(line).blockFormat()


def _char_format(editor: QPlainTextEdit, line: int, col: int):
    block = editor.document().findBlockByNumber(line)
    cursor = editor.textCursor()
    cursor.setPosition(block.position() + col + 1)  # reads the char before
    return cursor.charFormat()


# ── What each side shows ─────────────────────────────────────────────────────


def test_the_left_is_the_file_as_it_was(qtbot):
    editor = _rendered(qtbot, REPLACED, LEFT)

    assert _lines(editor) == ["  10  context", "  11  old one", "  12  old two", ""]


def test_the_right_is_the_file_as_it_is(qtbot):
    editor = _rendered(qtbot, REPLACED, RIGHT)

    assert _lines(editor) == [
        "  20  context",
        "  21  new one",
        "  22  new two",
        "  23  new three",
    ]


def test_context_appears_on_both_sides(qtbot):
    """Repeating it is the cost of the layout: a context line missing from one
    side would push everything under it out of step."""
    hunk = Hunk(header="@@ -1,2 +1,2 @@", lines=[(" ", "a\n"), (" ", "b\n")])

    assert _lines(_rendered(qtbot, hunk, LEFT)) == _lines(_rendered(qtbot, hunk, RIGHT))


# ── Staying level ────────────────────────────────────────────────────────────


def test_both_sides_render_the_same_number_of_lines(qtbot):
    left = _rendered(qtbot, REPLACED, LEFT)
    right = _rendered(qtbot, REPLACED, RIGHT)

    assert left.document().blockCount() == right.document().blockCount()


def test_both_editors_get_the_same_height(qtbot):
    """Equal line counts only line up while the boxes are the same size."""
    _host, editors = _pane(qtbot, REPLACED)

    assert len(editors) == 2
    assert editors[0].height() == editors[1].height() > 0


def test_a_padded_row_is_painted_as_filler_not_as_an_empty_line(qtbot):
    """Left blank because three lines were added, not because the file has a
    blank line there — those have to look different."""
    editor = _rendered(qtbot, REPLACED, LEFT)

    filler = make_filler_format().background().color()
    assert _block_format(editor, 3).background().color() == filler
    assert _block_format(editor, 0).background().color() != filler  # the context row


def test_the_sides_are_split_evenly(qtbot):
    _host, editors = _pane(qtbot, REPLACED)
    layout = editors[0].parentWidget().layout()

    assert layout.stretch(0) == layout.stretch(1) == 1


# ── Colour ───────────────────────────────────────────────────────────────────


def test_a_removal_is_tinted_on_the_left_and_an_addition_on_the_right(qtbot):
    formats = make_diff_formats()
    left = _rendered(qtbot, REPLACED, LEFT)
    right = _rendered(qtbot, REPLACED, RIGHT)

    assert _block_format(left, 1).background().color() == formats.blk_removed.background().color()
    assert _block_format(right, 1).background().color() == formats.blk_added.background().color()
    # Context keeps the plain background on both sides.
    assert _block_format(left, 0).background() == formats.blk_default.background()


def test_a_rewritten_line_gets_the_word_overlay_on_both_sides(qtbot):
    hunk = Hunk(
        header="@@ -1,1 +1,1 @@",
        lines=[("-", "value = 1\n"), ("+", "value = 2\n")],
    )
    syntax = make_syntax_formats()
    left = _rendered(qtbot, hunk, LEFT, filename="x.py")
    right = _rendered(qtbot, hunk, RIGHT, filename="x.py")

    # "value = " is shared; the digit is what changed. Prefix is 6 chars.
    changed_col = 6 + len("value = ")
    assert (
        _char_format(left, 0, changed_col).background().color()
        == syntax.removed_word_overlay.background().color()
    )
    assert (
        _char_format(right, 0, changed_col).background().color()
        == syntax.added_word_overlay.background().color()
    )
    # The shared words are not tinted.
    assert (
        _char_format(left, 0, 6).background().color()
        != syntax.removed_word_overlay.background().color()
    )


def test_a_line_with_no_counterpart_gets_no_word_overlay(qtbot):
    """There is nothing to compare it against, and tinting it whole would say
    every word changed."""
    hunk = Hunk(header="@@ -0,0 +1,1 @@", lines=[("+", "value = 2\n")])
    syntax = make_syntax_formats()
    right = _rendered(qtbot, hunk, RIGHT, filename="x.py")

    overlay = syntax.added_word_overlay.background().color()
    assert all(_char_format(right, 0, col).background().color() != overlay for col in range(6, 14))


def test_syntax_colouring_reaches_both_sides(qtbot):
    hunk = Hunk(header="@@ -1,1 +1,1 @@", lines=[("-", "def f():\n"), ("+", "def g():\n")])
    keyword = make_syntax_formats().keyword.foreground().color().name()

    for side in (LEFT, RIGHT):
        editor = _rendered(qtbot, hunk, side, filename="x.py")
        assert _char_format(editor, 0, 6).foreground().color().name() == keyword


# ── The pane ─────────────────────────────────────────────────────────────────


def test_both_editors_hide_their_own_scrollbars(qtbot):
    """The pane's one shared bar drives them; a bar of their own would let the
    sides scroll apart, which is the one thing this view must not do."""
    from PySide6.QtCore import Qt

    _host, editors = _pane(qtbot, REPLACED)

    for editor in editors:
        assert editor.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert editor.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff


def test_the_header_row_sits_above_the_panes(qtbot):
    host, editors = _pane(qtbot, REPLACED)
    layout = host.layout()

    assert layout.count() == 2
    assert layout.itemAt(1).widget() is editors[0].parentWidget()


def test_an_empty_hunk_still_builds(qtbot):
    _host, editors = _pane(qtbot, Hunk(header="@@ -0,0 +0,0 @@", lines=[]))

    assert [e.toPlainText() for e in editors] == ["", ""]


# ── Long hunks ───────────────────────────────────────────────────────────────


def test_a_long_hunk_renders_its_first_slice_now_and_the_rest_after(qtbot):
    """Otherwise a generated file freezes the window while it draws."""
    hunk = Hunk(header="@@ -1,250 +1,250 @@", lines=[(" ", f"line {i}\n") for i in range(250)])
    editor = QPlainTextEdit()
    qtbot.addWidget(editor)

    counted = render_side(editor.textCursor(), align_hunk(hunk), LEFT, make_diff_formats())

    assert counted == 250, "the height has to be known before the rest renders"
    assert len(_lines(editor)) == 100
    qtbot.waitUntil(lambda: len(_lines(editor)) == 250)


def test_a_long_hunk_is_sized_for_every_row_not_just_the_rendered_slice(qtbot):
    """Only the first hundred rows are on screen when the height is set. Sizing
    from what the document holds at that moment would leave the hunk clipped to
    a fifth of itself, with the rest unreachable."""
    hunk = Hunk(
        header="@@ -1,150 +1,300 @@",
        lines=[("-", f"old {i}\n") for i in range(150)] + [("+", f"new {i}\n") for i in range(300)],
    )
    rows = len(align_hunk(hunk))  # 300: the 150 removals pair off, the rest pad

    _host, editors = _pane(qtbot, hunk)

    line_height = editors[0].fontMetrics().lineSpacing()
    assert editors[0].height() == editors[1].height()
    assert editors[0].height() >= rows * line_height
