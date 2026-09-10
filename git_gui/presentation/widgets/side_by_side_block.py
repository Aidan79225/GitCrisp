# git_gui/presentation/widgets/side_by_side_block.py
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

Nothing selects this yet; the View-menu preference that reaches it is the
wiring layer.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QTextBlockFormat
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from git_gui.domain.entities import Hunk
from git_gui.presentation.theme import connect_widget, get_theme_manager
from git_gui.presentation.widgets.diff_block import (
    DiffFormats,
    SyntaxFormats,
    apply_syntax_tokens,
    apply_word_overlay,
    make_diff_editor,
    make_diff_formats,
    make_hunk_header_row,
    make_syntax_formats,
)
from git_gui.presentation.widgets.side_by_side import Row, align_hunk

LEFT = 0
RIGHT = 1

# Rows per slice of a long hunk. The unified renderer uses the same figure:
# enough that ordinary hunks land in one pass, small enough that a generated
# file does not freeze the window while it renders.
_CHUNK_SIZE = 100

# The two panes are separated by a gap rather than a line: a border here would
# read as part of the code, and the changed backgrounds already divide them.
PANE_GAP = 8


def make_filler_format() -> QTextBlockFormat:
    """The background of a row that exists only to keep the sides level.

    It has to be visibly not-code — an unpainted row reads as an empty line in
    the file, which is exactly the wrong thing to say about a line that was
    added on the other side.
    """
    fmt = QTextBlockFormat()
    fmt.setBackground(get_theme_manager().current.colors.as_qcolor("surface_variant"))
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
        cursor.setBlockFormat(filler)
        cursor.setCharFormat(formats.fmt_default)
        cursor.insertText("\n")
        return

    if not cell.changed:
        block_format, char_format = formats.blk_default, formats.fmt_default
    elif side == LEFT:
        block_format, char_format = formats.blk_removed, formats.fmt_removed
    else:
        block_format, char_format = formats.blk_added, formats.fmt_added
    cursor.setBlockFormat(block_format)
    cursor.setCharFormat(char_format)

    prefix = f"{cell.number:>4}  "
    content_start = cursor.position() + len(prefix)
    cursor.insertText(prefix + cell.text + "\n")

    if syntax_formats is None or filename is None:
        return
    apply_syntax_tokens(cursor.document(), content_start, cell.text, filename, syntax_formats)

    # A row changed on both sides is one line rewritten, and only there does
    # asking which words moved mean anything.
    other = row[RIGHT if side == LEFT else LEFT]
    if not cell.changed or other is None or not other.changed:
        return
    from git_gui.presentation.widgets.word_diff import pair_diff

    left_cell, right_cell = row
    assert left_cell is not None and right_cell is not None  # both changed
    left_spans, right_spans = pair_diff(left_cell.text, right_cell.text)
    spans, overlay = (
        (left_spans, syntax_formats.removed_word_overlay)
        if side == LEFT
        else (right_spans, syntax_formats.added_word_overlay)
    )
    apply_word_overlay(cursor.document(), content_start, spans, overlay)


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
    total = len(rows)

    def render_range(start: int, end: int) -> None:
        for index in range(start, end):
            _render_row(cursor, rows[index], side, formats, filler, syntax_formats, filename)

    render_range(0, min(_CHUNK_SIZE, total))
    if total <= _CHUNK_SIZE:
        return total

    from PySide6.QtCore import QTimer

    # Tied to the document, as the unified renderer is: when the block is torn
    # down mid-render the document goes with it and Qt drops the pending call,
    # rather than the callback reaching a dangling pointer.
    document = cursor.document()
    state = {"start": _CHUNK_SIZE}

    def next_chunk() -> None:
        try:
            start = state["start"]
            end = min(start + _CHUNK_SIZE, total)
            render_range(start, end)
            state["start"] = end
            if end < total:
                QTimer.singleShot(0, document, next_chunk)
        except RuntimeError:
            pass

    QTimer.singleShot(0, document, next_chunk)
    return total


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

        line_height = editors[0].fontMetrics().lineSpacing()
        margins = editors[0].contentsMargins()
        doc_margin = editors[0].document().documentMargin() * 2
        height = int(len(rows) * line_height + doc_margin + margins.top() + margins.bottom() + 4)
        for editor in editors:
            editor.setFixedHeight(max(height, 4))

    render(formats, syntax_formats)

    def rebuild() -> None:
        restyle_header()
        render(make_diff_formats(), make_syntax_formats() if syntax_formats is not None else None)

    connect_widget(panes, rebuild=rebuild)

    parent_layout.addWidget(header_row)
    parent_layout.addWidget(panes)
