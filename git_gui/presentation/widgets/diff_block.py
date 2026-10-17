"""Shared helpers for rendering diff hunks in both commit-detail and working-tree views."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cached_property

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPainter, QTextBlockFormat, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class _ElidedLabel(QLabel):
    """A one-line header that gives up width it cannot have, eliding its text.

    A plain QLabel's minimum width is its whole text. Inside a resizable scroll
    area that minimum widened the block, and every editor in it, past the pane,
    pushing the hunk's buttons out of view behind a second scrollbar. This one
    still asks for its whole text when there is room; when there is not, it
    shows what fits and keeps the rest in its tooltip.
    """

    def __init__(self, text: str, elide_mode: Qt.TextElideMode, parent=None) -> None:
        super().__init__(text, parent)
        self._elide_mode = elide_mode

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        fits = self.fontMetrics().horizontalAdvance(self.text()) <= self.contentsRect().width()
        self.setToolTip("" if fits else self.text())

    def paintEvent(self, event) -> None:
        rect = self.contentsRect()
        shown = self.fontMetrics().elidedText(self.text(), self._elide_mode, rect.width())
        painter = QPainter(self)
        self.style().drawItemText(
            painter,
            rect,
            self.alignment(),
            self.palette(),
            self.isEnabled(),
            shown,
            self.foregroundRole(),
        )


class _ClickableLabel(_ElidedLabel):
    """A header label that calls a callback on left-click and shows a pointer cursor."""

    def __init__(
        self, text: str, elide_mode: Qt.TextElideMode, on_click: Callable[[], None], parent=None
    ) -> None:
        super().__init__(text, elide_mode, parent)
        self._on_click = on_click
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self._on_click()
            ev.accept()
            return
        super().mousePressEvent(ev)


from git_gui.domain.entities import Hunk, LineKind
from git_gui.presentation.theme import ColorRole, connect_widget, get_theme_manager
from git_gui.presentation.widgets import word_diff
from git_gui.presentation.widgets._collapse_toggle import _CollapseToggle
from git_gui.presentation.widgets.side_by_side import (
    NO_NEWLINE_MARKERS,
    no_newline_note,
    parse_hunk_header,
)

# Style constants


def _file_block_style() -> str:
    c = get_theme_manager().current.colors
    return (
        f"QFrame#fileBlock {{ border: 1px solid {c.outline}; "
        f"border-radius: 4px; background-color: {c.surface_container_high}; }}"
    )


def _header_style() -> str:
    c = get_theme_manager().current.colors
    return f"color: {c.diff_file_header_fg}; font-weight: bold;"


def _hunk_header_color() -> str:
    return get_theme_manager().current.colors.diff_hunk_header_fg


HEADER_ROW_HEIGHT = 22  # consistent height for file + hunk header rows
HEADER_ROW_VPAD = 3  # top/bottom padding inside the header row

_LONG_LINE_LIMIT = 2000


# Diff format dataclass


@dataclass
class DiffFormats:
    fmt_added: QTextCharFormat
    fmt_removed: QTextCharFormat
    fmt_header: QTextCharFormat
    fmt_default: QTextCharFormat
    blk_added: QTextBlockFormat
    blk_removed: QTextBlockFormat
    blk_default: QTextBlockFormat


@dataclass
class SyntaxFormats:
    keyword: QTextCharFormat
    function: QTextCharFormat
    class_: QTextCharFormat
    string: QTextCharFormat
    number: QTextCharFormat
    comment: QTextCharFormat
    operator: QTextCharFormat
    decorator: QTextCharFormat
    # Word-level overlays (set BackgroundColor only — merge over line bg + syntax fg)
    added_word_overlay: QTextCharFormat
    removed_word_overlay: QTextCharFormat


# Maps the syntax_highlighter SyntaxToken.kind string → a SyntaxFormats attribute name.
_KIND_TO_ATTR = {
    "syntax_keyword": "keyword",
    "syntax_function": "function",
    "syntax_class": "class_",
    "syntax_string": "string",
    "syntax_number": "number",
    "syntax_comment": "comment",
    "syntax_operator": "operator",
    "syntax_decorator": "decorator",
}


# Factories


def make_file_block(
    path: str,
    on_header_clicked: Callable[[], None] | None = None,
    on_header_context_menu: Callable[[object], None] | None = None,
    on_state_changed: Callable[[bool], None] | None = None,
) -> tuple[QFrame, QVBoxLayout]:
    """Return a bordered QFrame with an amber file-header label and its inner layout.

    If *on_header_clicked* is given, the file header label becomes clickable
    (left-click invokes the callback) and shows a pointing cursor.
    """
    frame = QFrame()
    frame.setObjectName("fileBlock")
    frame.setFrameShape(QFrame.StyledPanel)
    frame.setStyleSheet(_file_block_style())
    # Don't let the frame grow beyond its content (avoids stretched short hunks)
    frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
    inner = QVBoxLayout(frame)
    inner.setContentsMargins(8, 6, 8, 6)
    inner.setSpacing(2)

    # Wrap the header label in a row container so its layout matches the
    # hunk header rows below — keeps heights consistent.
    header_row = QWidget()
    header_row_layout = QHBoxLayout(header_row)
    header_row_layout.setContentsMargins(0, HEADER_ROW_VPAD, 0, HEADER_ROW_VPAD)
    header_row_layout.setSpacing(4)
    toggle = _CollapseToggle(expanded=True)
    header_row_layout.addWidget(toggle)
    label_text = f"\U0001f4c4 {path}"
    # Eliding the middle keeps both the top folder and the file name in view.
    if on_header_clicked is not None:
        header_label = _ClickableLabel(label_text, Qt.ElideMiddle, on_header_clicked)
    else:
        header_label = _ElidedLabel(label_text, Qt.ElideMiddle)
    header_label.setStyleSheet(_header_style())
    header_row_layout.addWidget(header_label)
    header_row_layout.addStretch()
    header_row.setFixedHeight(HEADER_ROW_HEIGHT + HEADER_ROW_VPAD * 2)
    if on_header_context_menu is not None:
        header_row.setContextMenuPolicy(Qt.CustomContextMenu)
        header_row.customContextMenuRequested.connect(
            lambda pos: on_header_context_menu(header_row.mapToGlobal(pos))
        )
    inner.addWidget(header_row)

    def _set_expanded(expanded: bool) -> None:
        for i in range(1, inner.count()):
            item = inner.itemAt(i)
            w = item.widget() if item else None
            if w is not None:
                w.setVisible(expanded)
        if on_state_changed is not None:
            on_state_changed(expanded)

    toggle.state_changed.connect(_set_expanded)

    def _rebuild() -> None:
        frame.setStyleSheet(_file_block_style())
        header_label.setStyleSheet(_header_style())

    connect_widget(frame, rebuild=_rebuild)

    return frame, inner


def make_diff_formats() -> DiffFormats:
    """Return a DiffFormats dataclass with all QTextCharFormat / QTextBlockFormat objects."""
    c = get_theme_manager().current.colors
    on_surface = c.as_qcolor(ColorRole.ON_SURFACE)

    fmt_added = QTextCharFormat()
    fmt_added.setForeground(on_surface)

    fmt_removed = QTextCharFormat()
    fmt_removed.setForeground(on_surface)

    fmt_header = QTextCharFormat()
    fmt_header.setForeground(QColor(_hunk_header_color()))

    fmt_default = QTextCharFormat()
    fmt_default.setForeground(on_surface)

    blk_added = QTextBlockFormat()
    blk_added.setBackground(c.as_qcolor(ColorRole.DIFF_ADDED_OVERLAY))

    blk_removed = QTextBlockFormat()
    blk_removed.setBackground(c.as_qcolor(ColorRole.DIFF_REMOVED_OVERLAY))

    blk_default = QTextBlockFormat()

    return DiffFormats(
        fmt_added=fmt_added,
        fmt_removed=fmt_removed,
        fmt_header=fmt_header,
        fmt_default=fmt_default,
        blk_added=blk_added,
        blk_removed=blk_removed,
        blk_default=blk_default,
    )


def make_syntax_formats() -> SyntaxFormats:
    """Build a SyntaxFormats dataclass from the active theme's palette."""
    c = get_theme_manager().current.colors

    def _fg(role: str) -> QTextCharFormat:
        f = QTextCharFormat()
        f.setForeground(c.as_qcolor(role))
        return f

    def _bg(role: str) -> QTextCharFormat:
        f = QTextCharFormat()
        f.setBackground(c.as_qcolor(role))
        return f

    return SyntaxFormats(
        keyword=_fg("syntax_keyword"),
        function=_fg("syntax_function"),
        class_=_fg("syntax_class"),
        string=_fg("syntax_string"),
        number=_fg("syntax_number"),
        comment=_fg("syntax_comment"),
        operator=_fg("syntax_operator"),
        decorator=_fg("syntax_decorator"),
        added_word_overlay=_bg("diff_added_word_overlay"),
        removed_word_overlay=_bg("diff_removed_word_overlay"),
    )


def make_diff_editor() -> QPlainTextEdit:
    """Return a configured read-only no-wrap monospace QPlainTextEdit for diff display."""
    editor = QPlainTextEdit()
    editor.setReadOnly(True)
    editor.setLineWrapMode(QPlainTextEdit.NoWrap)
    editor.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    # Only the family is fixed here, so the size still follows the theme's
    # typography scale.
    editor.setStyleSheet(
        "QPlainTextEdit { font-family: 'Consolas', 'Courier New', 'Menlo', 'Monaco', monospace; }"
    )
    return editor


def fit_height_to_lines(editor: QPlainTextEdit, line_count: int) -> None:
    """Size *editor* to show *line_count* lines in its current font without scrolling."""
    line_height = editor.fontMetrics().lineSpacing()
    margins = editor.contentsMargins()
    doc_margin = editor.document().documentMargin() * 2
    total_height = int(line_count * line_height + doc_margin + margins.top() + margins.bottom() + 4)
    editor.setFixedHeight(max(total_height, 4))


# Hunk rendering helpers


def render_hunk_header_line(cursor, hunk: Hunk, formats: DiffFormats) -> None:
    """Insert the @@ header line of *hunk* into *cursor* using the header char format."""
    cursor.setBlockFormat(formats.blk_default)
    cursor.setCharFormat(formats.fmt_header)
    cursor.insertText(hunk.header + "\n")


_CHUNK_SIZE = 100

# As wide as a numbered line's "1234 1234  ", so a note lines up with the code.
_UNNUMBERED_GUTTER = " " * 11


def _too_long_to_highlight(text: str) -> bool:
    """Whether colouring *text* would cost more than the colour is worth.

    Both the syntax and the word pass grow with the length of the line, and a
    minified file is mostly one line tens of thousands of characters long.
    """
    return len(text) + 1 > _LONG_LINE_LIMIT


def changed_word_spans(
    old: str, new: str
) -> tuple[list[word_diff.WordSpan], list[word_diff.WordSpan]] | None:
    """Word-diff one rewritten line, or None when either side is too long to try.

    The word diff is roughly quadratic in tokens, so a rebuilt minified bundle
    held the window for seconds while its block rendered.
    """
    if _too_long_to_highlight(old) or _too_long_to_highlight(new):
        return None
    return word_diff.pair_diff(old, new)


@dataclass(frozen=True)
class _Rewrite:
    """A removed line and the added line that replaced it.

    Both lines of the pair look it up, so the word diff is worked out for the
    first and kept for the second.
    """

    old: str
    new: str

    @cached_property
    def spans(self) -> tuple[list[word_diff.WordSpan], list[word_diff.WordSpan]] | None:
        return changed_word_spans(self.old, self.new)


def _build_pair_index(lines: list[tuple[str, str]]) -> dict[int, _Rewrite]:
    """Map the indices of paired -/+ lines to the rewrite they belong to.

    A change is every '-' and '+' line between two context lines, and its i-th
    removed line pairs with its i-th added line, as align_hunk pairs them for
    the side-by-side view. A no-newline note is not a line and does not end
    the change. Both indices map to the same rewrite so the renderer can look
    up either side.
    """
    pairs: dict[int, _Rewrite] = {}
    removed: list[int] = []
    added: list[int] = []

    def close_change() -> None:
        for old_index, new_index in zip(removed, added, strict=False):
            rewrite = _Rewrite(lines[old_index][1].rstrip("\n"), lines[new_index][1].rstrip("\n"))
            pairs[old_index] = rewrite
            pairs[new_index] = rewrite
        removed.clear()
        added.clear()

    for index, (origin, _) in enumerate(lines):
        if origin == LineKind.REMOVED:
            removed.append(index)
        elif origin == LineKind.ADDED:
            added.append(index)
        elif origin not in NO_NEWLINE_MARKERS:
            close_change()
    close_change()
    return pairs


def apply_syntax_tokens(
    document,
    content_start: int,
    text: str,
    filename: str,
    syntax_formats: SyntaxFormats,
) -> None:
    """Layer Pygments colours over *text* already inserted at *content_start*.

    Shared by the unified and side-by-side renderers so one line reads the same
    in both. A very long line is left alone: tokenizing it costs more than the
    colour is worth, and minified files are mostly one such line.
    """
    from git_gui.presentation.widgets.syntax_highlighter import tokenize

    if not text or _too_long_to_highlight(text):
        return
    positions = _qt_positions(text)
    for tok in tokenize(text, filename):
        attr = _KIND_TO_ATTR.get(tok.kind)
        if attr is None:
            continue
        _merge_char_format(
            document,
            content_start + positions[tok.start],
            content_start + positions[tok.end],
            getattr(syntax_formats, attr),
        )


def apply_word_overlay(document, content_start: int, text: str, spans, overlay) -> None:
    """Tint the spans of *text* that a word-level diff marked as changed."""
    positions = _qt_positions(text)
    for span in spans:
        if span.kind != "changed":
            continue
        _merge_char_format(
            document,
            content_start + positions[span.start],
            content_start + positions[span.end],
            overlay,
        )


def _qt_positions(text: str) -> Sequence[int]:
    """Qt's position of each character index of *text*, and of its end.

    Python counts a character outside the Basic Multilingual Plane (most emoji)
    as one, but Qt counts its two UTF-16 units, so without this every colour
    after one landed a character early.
    """
    if len(text.encode("utf-16-le")) == 2 * len(text):
        return range(len(text) + 1)
    positions = [0]
    for ch in text:
        positions.append(positions[-1] + (2 if ord(ch) > 0xFFFF else 1))
    return positions


def _merge_char_format(document, start: int, end: int, char_format: QTextCharFormat) -> None:
    cursor = QTextCursor(document)
    cursor.setPosition(start)
    cursor.setPosition(end, QTextCursor.KeepAnchor)
    cursor.mergeCharFormat(char_format)


def _apply_rewrite_overlay(
    document, content_start: int, origin: str, rewrite: _Rewrite, syntax_formats: SyntaxFormats
) -> None:
    """Tint the words of one side of a rewritten line that the other side lacks."""
    spans = rewrite.spans
    if spans is None:
        return
    old_spans, new_spans = spans
    if origin == LineKind.REMOVED:
        apply_word_overlay(
            document, content_start, rewrite.old, old_spans, syntax_formats.removed_word_overlay
        )
    else:
        apply_word_overlay(
            document, content_start, rewrite.new, new_spans, syntax_formats.added_word_overlay
        )


def _render_no_newline_note(cursor, content: str, formats: DiffFormats) -> None:
    """git's note that the line above ends without a newline: unnumbered, not code."""
    cursor.setBlockFormat(formats.blk_default)
    cursor.setCharFormat(formats.fmt_default)
    cursor.insertText(_UNNUMBERED_GUTTER + no_newline_note(content) + "\n")


def _render_lines_range(
    cursor,
    hunk,
    formats,
    start,
    end,
    syntax_formats=None,
    filename=None,
    pair_index=None,
) -> None:
    """Render hunk.lines[start:end] into cursor, tracking line numbers.

    When *syntax_formats* and *filename* are both given, layer Pygments-driven
    syntax coloring onto the inserted content via mergeCharFormat.
    When *pair_index* is given, also apply a word-level overlay to changed
    spans of paired -/+ lines.
    """
    old_line, new_line = parse_hunk_header(hunk.header)
    for origin, _ in hunk.lines[:start]:
        if origin == LineKind.ADDED:
            new_line += 1
        elif origin == LineKind.REMOVED:
            old_line += 1
        elif origin not in NO_NEWLINE_MARKERS:
            old_line += 1
            new_line += 1

    apply_syntax = syntax_formats is not None and filename is not None
    pair_index = pair_index or {}

    for idx in range(start, end):
        origin, content = hunk.lines[idx]
        if origin == LineKind.ADDED:
            cursor.setBlockFormat(formats.blk_added)
            cursor.setCharFormat(formats.fmt_added)
            prefix = f"     {new_line:>4}  "
            new_line += 1
        elif origin == LineKind.REMOVED:
            cursor.setBlockFormat(formats.blk_removed)
            cursor.setCharFormat(formats.fmt_removed)
            prefix = f"{old_line:>4}       "
            old_line += 1
        elif origin in NO_NEWLINE_MARKERS:
            _render_no_newline_note(cursor, content, formats)
            continue
        else:
            cursor.setBlockFormat(formats.blk_default)
            cursor.setCharFormat(formats.fmt_default)
            prefix = f"{old_line:>4} {new_line:>4}  "
            old_line += 1
            new_line += 1

        line_with_eol = content if content.endswith("\n") else content + "\n"
        full_text = prefix + line_with_eol
        content_doc_start = cursor.position() + len(prefix)
        cursor.insertText(full_text)

        if not apply_syntax:
            continue

        content_text = line_with_eol.rstrip("\n")
        if not content_text:
            continue

        # Pass 2 — syntax tokens
        apply_syntax_tokens(
            cursor.document(), content_doc_start, content_text, filename, syntax_formats
        )

        # Pass 3 — word-level overlay (only for paired -/+)
        if idx in pair_index:
            _apply_rewrite_overlay(
                cursor.document(), content_doc_start, origin, pair_index[idx], syntax_formats
            )


def render_hunk_content_lines(
    cursor,
    hunk: Hunk,
    formats: DiffFormats,
    syntax_formats: SyntaxFormats | None = None,
    filename: str | None = None,
) -> int:
    """Insert the +/-/context lines of *hunk* into *cursor*.

    For small hunks (<= _CHUNK_SIZE lines), renders synchronously.
    For large hunks, renders the first chunk immediately and schedules
    the rest via QTimer.singleShot to keep the UI responsive.

    When *syntax_formats* and *filename* are both given, the syntax pass
    layers Pygments-driven coloring on each rendered line, and adjacent -/+
    line pairs receive a word-level overlay highlighting changed spans.
    """
    if not hunk.lines:
        return 0

    pair_index = _build_pair_index(hunk.lines) if syntax_formats and filename else {}

    total = len(hunk.lines)
    if total <= _CHUNK_SIZE:
        _render_lines_range(
            cursor,
            hunk,
            formats,
            0,
            total,
            syntax_formats=syntax_formats,
            filename=filename,
            pair_index=pair_index,
        )
        return total

    _render_lines_range(
        cursor,
        hunk,
        formats,
        0,
        _CHUNK_SIZE,
        syntax_formats=syntax_formats,
        filename=filename,
        pair_index=pair_index,
    )

    from PySide6.QtCore import QTimer

    state = {"start": _CHUNK_SIZE}

    # The cursor's document is the context: when its parent widget is deleted
    # (e.g. _clear_blocks during commit/repo switch), the document is destroyed
    # and Qt cancels the pending callback. Without this guard the callback fires
    # and dereferences a dangling QTextDocument → access violation on Windows.
    document = cursor.document()

    def _next_chunk():
        try:
            start = state["start"]
            end = min(start + _CHUNK_SIZE, total)
            _render_lines_range(
                cursor,
                hunk,
                formats,
                start,
                end,
                syntax_formats=syntax_formats,
                filename=filename,
                pair_index=pair_index,
            )
            state["start"] = end
            if end < total:
                QTimer.singleShot(0, document, _next_chunk)
        except RuntimeError:
            pass

    QTimer.singleShot(0, document, _next_chunk)
    return total


def render_hunk_lines(cursor, hunk: Hunk, formats: DiffFormats) -> int:
    """Render one complete hunk (header line + content lines) into *cursor*.

    Returns the total number of lines inserted (1 header + len(hunk.lines) content).
    """
    render_hunk_header_line(cursor, hunk, formats)
    content_count = render_hunk_content_lines(cursor, hunk, formats)
    return 1 + content_count


# Shared per-hunk widget builder


def make_hunk_header_row(
    hunk: Hunk,
    *,
    extra_left_widgets: list[QWidget] | None = None,
    extra_right_widgets: list[QWidget] | None = None,
    on_header_clicked: Callable[[], None] | None = None,
) -> tuple[QWidget, Callable[[], None]]:
    """Return the @@ row that sits above a hunk, and a restyle callback.

    The callback comes back because the label's colour is set inline rather
    than through the stylesheet, so a theme change has to reapply it.
    """
    header_row = QWidget()
    header_layout = QHBoxLayout(header_row)
    header_layout.setContentsMargins(0, HEADER_ROW_VPAD, 0, HEADER_ROW_VPAD)
    header_layout.setSpacing(4)
    for w in extra_left_widgets or []:
        header_layout.addWidget(w)
    header_text = hunk.header.strip()
    if on_header_clicked is not None:
        header_label: QLabel = _ClickableLabel(header_text, Qt.ElideRight, on_header_clicked)
    else:
        header_label = _ElidedLabel(header_text, Qt.ElideRight)
    header_label.setStyleSheet(f"color: {_hunk_header_color()};")
    header_layout.addWidget(header_label)
    header_layout.addStretch()
    for w in extra_right_widgets or []:
        header_layout.addWidget(w)
    header_row.setFixedHeight(HEADER_ROW_HEIGHT + HEADER_ROW_VPAD * 2)

    def restyle() -> None:
        header_label.setStyleSheet(f"color: {_hunk_header_color()};")

    return header_row, restyle


def add_hunk_widget(
    parent_layout: QVBoxLayout,
    hunk: Hunk,
    formats: DiffFormats,
    *,
    extra_left_widgets: list[QWidget] | None = None,
    extra_right_widgets: list[QWidget] | None = None,
    on_header_clicked: Callable[[], None] | None = None,
    on_header_context_menu: Callable[[object], None] | None = None,
    syntax_formats: SyntaxFormats | None = None,
    filename: str | None = None,
) -> None:
    """Append a header row + sized-to-fit diff editor for one hunk into parent_layout.

    When *syntax_formats* and *filename* are both given, the diff editor renders
    with Pygments syntax highlighting and word-level intra-line diff.
    """
    if extra_left_widgets is None:
        extra_left_widgets = []
    if extra_right_widgets is None:
        extra_right_widgets = []

    # --- Header row ---
    header_row, restyle_header = make_hunk_header_row(
        hunk,
        extra_left_widgets=extra_left_widgets,
        extra_right_widgets=extra_right_widgets,
        on_header_clicked=on_header_clicked,
    )

    # --- Diff editor ---
    editor = make_diff_editor()

    def _render(current_formats: DiffFormats, current_syntax: SyntaxFormats | None) -> None:
        editor.clear()
        cursor = editor.textCursor()
        line_count = render_hunk_content_lines(
            cursor,
            hunk,
            current_formats,
            syntax_formats=current_syntax,
            filename=filename,
        )
        editor.setTextCursor(cursor)
        # Measured on every render: a typography change arrives as a theme
        # change, with the new font already set on the editor.
        fit_height_to_lines(editor, line_count)

    _render(formats, syntax_formats)
    editor.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def _rebuild() -> None:
        restyle_header()
        # Rebuild syntax_formats from the new theme too — but only if syntax was active.
        _render(make_diff_formats(), make_syntax_formats() if syntax_formats is not None else None)

    connect_widget(editor, rebuild=_rebuild)

    parent_layout.addWidget(header_row)
    parent_layout.addWidget(editor)


def make_overflow_notice(hidden: int) -> QLabel:
    """A muted one-line notice standing in for files beyond the block cap."""
    label = QLabel(
        f"+ {hidden} more changed file{'s' if hidden != 1 else ''} not shown — "
        "select a file above to view its diff."
    )
    label.setWordWrap(True)
    label.setContentsMargins(8, 8, 8, 8)
    return label


def make_skeleton_container() -> QWidget:
    """Return a QWidget containing 4 gray placeholder bars that mimic diff rows.

    Used as a placeholder inside a file block while the real hunks are being loaded.
    """
    from PySide6.QtWidgets import QFrame, QVBoxLayout

    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(8, 6, 8, 6)
    layout.setSpacing(4)
    for _ in (90, 60, 75, 50):
        bar = QFrame()
        bar.setFixedHeight(10)
        bar.setMinimumWidth(40)
        bar.setStyleSheet("background-color: rgba(128, 128, 128, 40); border-radius: 3px;")
        layout.addWidget(bar)
    return container
