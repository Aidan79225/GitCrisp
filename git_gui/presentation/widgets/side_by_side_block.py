"""One hunk drawn as two panes instead of one column.

The unified block interleaves both versions of a change, so reading it means
holding the old lines in your head while your eye walks down to the new ones.
Two panes put them at the same height: the file as it was on the left, as it
is on the right, and a change reads across rather than down.

What makes that work is `align_hunk` — the rows it returns already have the
shorter side of a change padded, so both sides render the same number of lines
and stay level all the way down the hunk. Nothing here re-derives that.

Both editors are ordinary hunk editors with their scrollbars off, so the pane's
one horizontal bar (SharedHScroll) finds them and drives them together — which
is what keeps the two sides showing the same columns of a long line.

`hunk_view.add_hunk_view` is the one place that chooses this view over the
unified one, from the View-menu preference.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QTextBlockFormat, QTextCharFormat
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from git_gui.domain.entities import Hunk
from git_gui.presentation.theme import ColorRole, connect_widget, get_theme_manager
from git_gui.presentation.widgets.diff_block import (
    DiffFormats,
    SyntaxFormats,
    apply_syntax_tokens,
    apply_word_overlay,
    changed_word_spans,
    fit_height_to_lines,
    make_diff_editor,
    make_diff_formats,
    make_hunk_header_row,
    make_syntax_formats,
    render_in_chunks,
)
from git_gui.presentation.widgets.side_by_side import Cell, Row, align_hunk
from git_gui.presentation.widgets.word_diff import WordSpan

LEFT = 0
RIGHT = 1

# The two panes are separated by a gap rather than a line: a border here would
# read as part of the code, and the changed backgrounds already divide them.
PANE_GAP = 8

# As wide as a numbered row's "1234  ", so a note lines up with the code.
_UNNUMBERED_GUTTER = " " * 6


def make_filler_format() -> QTextBlockFormat:
    """The background of a row that exists only to keep the sides level.

    It has to be visibly not-code — an unpainted row reads as an empty line in
    the file, which is exactly the wrong thing to say about a line that was
    added on the other side.
    """
    fmt = QTextBlockFormat()
    fmt.setBackground(get_theme_manager().current.colors.as_qcolor(ColorRole.SURFACE_VARIANT))
    return fmt


def _render_row(
    cursor,
    row: Row,
    side: int,
    formats: DiffFormats,
    filler: QTextBlockFormat,
    syntax_formats: SyntaxFormats | None,
    filename: str | None,
) -> None:
    cell = row[side]
    if cell is None:
        _render_filler(cursor, formats, filler)
        return
    block_format, char_format = _cell_formats(cell, side, formats)
    cursor.setBlockFormat(block_format)
    cursor.setCharFormat(char_format)
    if cell.number is None:  # git's no-newline note: not code, so nothing to colour
        cursor.insertText(_UNNUMBERED_GUTTER + cell.text + "\n")
        return
    prefix = f"{cell.number:>4}  "
    content_start = cursor.position() + len(prefix)
    cursor.insertText(prefix + cell.text + "\n")
    if syntax_formats is not None and filename is not None:
        _highlight_cell(
            cursor.document(), content_start, row, side, cell.text, syntax_formats, filename
        )


def _render_filler(cursor, formats: DiffFormats, filler: QTextBlockFormat) -> None:
    cursor.setBlockFormat(filler)
    cursor.setCharFormat(formats.fmt_default)
    cursor.insertText("\n")


def _cell_formats(
    cell: Cell, side: int, formats: DiffFormats
) -> tuple[QTextBlockFormat, QTextCharFormat]:
    if not cell.changed:
        return formats.blk_default, formats.fmt_default
    if side == LEFT:
        return formats.blk_removed, formats.fmt_removed
    return formats.blk_added, formats.fmt_added


def _highlight_cell(
    document,
    content_start: int,
    row: Row,
    side: int,
    text: str,
    syntax_formats: SyntaxFormats,
    filename: str,
) -> None:
    """Colour the code of one cell, and the words a rewrite changed in it."""
    apply_syntax_tokens(document, content_start, text, filename, syntax_formats)
    spans = _rewritten_word_spans(row, side)
    if spans is None:
        return
    overlay = (
        syntax_formats.removed_word_overlay if side == LEFT else syntax_formats.added_word_overlay
    )
    apply_word_overlay(document, content_start, text, spans, overlay)


def _rewritten_word_spans(row: Row, side: int) -> list[WordSpan] | None:
    """The word spans of *side*, when *row* is one line rewritten.

    A row changed on both sides is one line rewritten, and only there does
    asking which words moved mean anything.
    """
    left, right = row
    if left is None or right is None or not (left.changed and right.changed):
        return None
    spans = changed_word_spans(left.text, right.text)
    return None if spans is None else spans[side]


def render_side(
    cursor,
    rows: list[Row],
    side: int,
    formats: DiffFormats,
    syntax_formats: SyntaxFormats | None = None,
    filename: str | None = None,
) -> int:
    """Render one side of *rows* into *cursor*, returning the line count.

    Long hunks render their first slice now and the rest through the event
    loop, so a big file does not hold the window. The count is returned up
    front either way: it is what both editors are sized to, and the two have
    to agree before the deferred slices land or the sides start level and
    then drift.
    """
    if not rows:
        return 0

    filler = make_filler_format()

    def render_range(start: int, end: int) -> None:
        for index in range(start, end):
            _render_row(cursor, rows[index], side, formats, filler, syntax_formats, filename)

    render_in_chunks(cursor.document(), len(rows), render_range)
    return len(rows)


def add_side_by_side_hunk_widget(
    parent_layout: QVBoxLayout,
    hunk: Hunk,
    formats: DiffFormats,
    *,
    extra_left_widgets: list[QWidget] | None = None,
    extra_right_widgets: list[QWidget] | None = None,
    on_header_clicked: Callable[[], None] | None = None,
    syntax_formats: SyntaxFormats | None = None,
    filename: str | None = None,
) -> None:
    """Append a header row and a two-pane view of one hunk to *parent_layout*.

    The counterpart of `add_hunk_widget`, and deliberately the same shape: the
    preference that chooses between them is a swap of one call.
    """
    rows = align_hunk(hunk)

    header_row, restyle_header = make_hunk_header_row(
        hunk,
        extra_left_widgets=extra_left_widgets,
        extra_right_widgets=extra_right_widgets,
        on_header_clicked=on_header_clicked,
    )

    panes = QWidget()
    panes_layout = QHBoxLayout(panes)
    panes_layout.setContentsMargins(0, 0, 0, 0)
    panes_layout.setSpacing(PANE_GAP)

    editors = []
    for _ in (LEFT, RIGHT):
        editor = make_diff_editor()
        editor.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        # Equal stretch: the two sides get the same width whatever they hold,
        # so a line sits at the same place on both.
        panes_layout.addWidget(editor, 1)
        editors.append(editor)

    def render(current_formats: DiffFormats, current_syntax: SyntaxFormats | None) -> None:
        for side, editor in enumerate(editors):
            editor.clear()
            cursor = editor.textCursor()
            render_side(
                cursor,
                rows,
                side,
                current_formats,
                syntax_formats=current_syntax,
                filename=filename,
            )
            editor.setTextCursor(cursor)

        for editor in editors:
            fit_height_to_lines(editor, len(rows))

    render(formats, syntax_formats)

    def rebuild() -> None:
        restyle_header()
        render(make_diff_formats(), make_syntax_formats() if syntax_formats is not None else None)

    connect_widget(panes, rebuild=rebuild)

    parent_layout.addWidget(header_row)
    parent_layout.addWidget(panes)
