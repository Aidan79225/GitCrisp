# git_gui/presentation/widgets/diff_block.py
"""Shared helpers for rendering diff hunks in both commit-detail and working-tree views."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextBlockFormat, QTextCharFormat
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QSizePolicy, QVBoxLayout, QWidget,
)


class _ClickableLabel(QLabel):
    """QLabel that calls a callback on left-click and shows a pointer cursor."""

    def __init__(self, text: str, on_click: Callable[[], None], parent=None) -> None:
        super().__init__(text, parent)
        self._on_click = on_click
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, ev) -> None:  # noqa: N802 (Qt API)
        if ev.button() == Qt.LeftButton:
            self._on_click()
            ev.accept()
            return
        super().mousePressEvent(ev)

from git_gui.domain.entities import Hunk
from git_gui.presentation.theme import get_theme_manager, connect_widget

# ---------------------------------------------------------------------------
# Style constants
# ---------------------------------------------------------------------------

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
HEADER_ROW_VPAD = 3      # top/bottom padding inside the header row

_LONG_LINE_LIMIT = 2000


# ---------------------------------------------------------------------------
# Diff format dataclass
# ---------------------------------------------------------------------------

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
    "syntax_keyword":   "keyword",
    "syntax_function":  "function",
    "syntax_class":     "class_",
    "syntax_string":    "string",
    "syntax_number":    "number",
    "syntax_comment":   "comment",
    "syntax_operator":  "operator",
    "syntax_decorator": "decorator",
}


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def make_file_block(
    path: str,
    on_header_clicked: Callable[[], None] | None = None,
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
    label_text = f"\U0001f4c4 {path}"
    if on_header_clicked is not None:
        header_label = _ClickableLabel(label_text, on_header_clicked)
    else:
        header_label = QLabel(label_text)
    header_label.setStyleSheet(_header_style())
    header_row_layout.addWidget(header_label)
    header_row_layout.addStretch()
    header_row.setFixedHeight(HEADER_ROW_HEIGHT + HEADER_ROW_VPAD * 2)
    inner.addWidget(header_row)

    def _rebuild() -> None:
        frame.setStyleSheet(_file_block_style())
        header_label.setStyleSheet(_header_style())

    connect_widget(frame, rebuild=_rebuild)

    return frame, inner


def make_diff_formats() -> DiffFormats:
    """Return a DiffFormats dataclass with all QTextCharFormat / QTextBlockFormat objects."""
    c = get_theme_manager().current.colors
    on_surface = c.as_qcolor("on_surface")

    fmt_added = QTextCharFormat()
    fmt_added.setForeground(on_surface)

    fmt_removed = QTextCharFormat()
    fmt_removed.setForeground(on_surface)

    fmt_header = QTextCharFormat()
    fmt_header.setForeground(QColor(_hunk_header_color()))

    fmt_default = QTextCharFormat()
    fmt_default.setForeground(on_surface)

    blk_added = QTextBlockFormat()
    blk_added.setBackground(c.as_qcolor("diff_added_overlay"))

    blk_removed = QTextBlockFormat()
    blk_removed.setBackground(c.as_qcolor("diff_removed_overlay"))

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
    # Apply monospace font via stylesheet — this survives the theme manager's
    # global w.setFont() pass that would otherwise override a setFont() call.
    editor.setStyleSheet(
        "QPlainTextEdit { font-family: 'Consolas', 'Courier New', 'Menlo', 'Monaco', monospace; }"
    )
    return editor


# ---------------------------------------------------------------------------
# Parse helpers
# ---------------------------------------------------------------------------

def parse_hunk_header(header: str) -> tuple[int, int]:
    """Return (old_start, new_start) line numbers parsed from a @@ header string."""
    m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", header)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 1, 1


# ---------------------------------------------------------------------------
# Hunk rendering helpers
# ---------------------------------------------------------------------------

def render_hunk_header_line(cursor, hunk: Hunk, formats: DiffFormats) -> None:
    """Insert the @@ header line of *hunk* into *cursor* using the header char format."""
    cursor.setBlockFormat(formats.blk_default)
    cursor.setCharFormat(formats.fmt_header)
    cursor.insertText(hunk.header + "\n")


_CHUNK_SIZE = 100


def _build_pair_index(lines: list[tuple[str, str]]) -> dict[int, tuple[str, str]]:
    """Map paired -/+ line indices to (old_content, new_content).

    A pair is formed only when a '-' line is immediately followed by a '+' line.
    Both indices map to the same (old, new) tuple so the renderer can look up
    either side.
    """
    pairs: dict[int, tuple[str, str]] = {}
    i = 0
    n = len(lines)
    while i < n - 1:
        if lines[i][0] == "-" and lines[i + 1][0] == "+":
            old = lines[i][1].rstrip("\n")
            new = lines[i + 1][1].rstrip("\n")
            pairs[i] = (old, new)
            pairs[i + 1] = (old, new)
            i += 2
        else:
            i += 1
    return pairs


def _render_lines_range(
    cursor, hunk, formats, start, end,
    syntax_formats=None, filename=None,
    pair_index=None,
) -> None:
    """Render hunk.lines[start:end] into cursor, tracking line numbers.

    When *syntax_formats* and *filename* are both given, layer Pygments-driven
    syntax coloring onto the inserted content via mergeCharFormat.
    When *pair_index* is given, also apply a word-level overlay to changed
    spans of paired -/+ lines.
    """
    from PySide6.QtGui import QTextCursor
    from git_gui.presentation.widgets.syntax_highlighter import tokenize
    from git_gui.presentation.widgets.word_diff import pair_diff

    old_line, new_line = parse_hunk_header(hunk.header)
    for origin, _ in hunk.lines[:start]:
        if origin == "+":
            new_line += 1
        elif origin == "-":
            old_line += 1
        else:
            old_line += 1
            new_line += 1

    apply_syntax = syntax_formats is not None and filename is not None
    pair_index = pair_index or {}

    for idx in range(start, end):
        origin, content = hunk.lines[idx]
        if origin == "+":
            cursor.setBlockFormat(formats.blk_added)
            cursor.setCharFormat(formats.fmt_added)
            prefix = f"     {new_line:>4}  "
            new_line += 1
        elif origin == "-":
            cursor.setBlockFormat(formats.blk_removed)
            cursor.setCharFormat(formats.fmt_removed)
            prefix = f"{old_line:>4}       "
            old_line += 1
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
        if len(line_with_eol) > _LONG_LINE_LIMIT:
            continue

        content_text = line_with_eol.rstrip("\n")
        if not content_text:
            continue

        # Pass 2 — syntax tokens
        tokens = tokenize(content_text, filename)
        for tok in tokens:
            tok_cursor = QTextCursor(cursor.document())
            tok_cursor.setPosition(content_doc_start + tok.start)
            tok_cursor.setPosition(
                content_doc_start + tok.end,
                QTextCursor.KeepAnchor,
            )
            attr = _KIND_TO_ATTR.get(tok.kind)
            if attr is None:
                continue
            tok_cursor.mergeCharFormat(getattr(syntax_formats, attr))

        # Pass 3 — word-level overlay (only for paired -/+)
        if idx not in pair_index or origin == " ":
            continue
        old_text, new_text = pair_index[idx]
        old_spans, new_spans = pair_diff(old_text, new_text)
        spans, overlay = (
            (old_spans, syntax_formats.removed_word_overlay)
            if origin == "-"
            else (new_spans, syntax_formats.added_word_overlay)
        )
        for span in spans:
            if span.kind != "changed":
                continue
            ws_cursor = QTextCursor(cursor.document())
            ws_cursor.setPosition(content_doc_start + span.start)
            ws_cursor.setPosition(
                content_doc_start + span.end,
                QTextCursor.KeepAnchor,
            )
            ws_cursor.mergeCharFormat(overlay)


def render_hunk_content_lines(
    cursor, hunk: Hunk, formats: DiffFormats,
    syntax_formats: "SyntaxFormats | None" = None,
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
            cursor, hunk, formats, 0, total,
            syntax_formats=syntax_formats, filename=filename,
            pair_index=pair_index,
        )
        return total

    _render_lines_range(
        cursor, hunk, formats, 0, _CHUNK_SIZE,
        syntax_formats=syntax_formats, filename=filename,
        pair_index=pair_index,
    )

    from PySide6.QtCore import QTimer
    state = {"start": _CHUNK_SIZE}

    def _next_chunk():
        try:
            start = state["start"]
            end = min(start + _CHUNK_SIZE, total)
            _render_lines_range(
                cursor, hunk, formats, start, end,
                syntax_formats=syntax_formats, filename=filename,
                pair_index=pair_index,
            )
            state["start"] = end
            if end < total:
                QTimer.singleShot(0, _next_chunk)
        except RuntimeError:
            pass

    QTimer.singleShot(0, _next_chunk)
    return total


def render_hunk_lines(cursor, hunk: Hunk, formats: DiffFormats) -> int:
    """Render one complete hunk (header line + content lines) into *cursor*.

    Returns the total number of lines inserted (1 header + len(hunk.lines) content).
    """
    render_hunk_header_line(cursor, hunk, formats)
    content_count = render_hunk_content_lines(cursor, hunk, formats)
    return 1 + content_count


# ---------------------------------------------------------------------------
# Shared per-hunk widget builder
# ---------------------------------------------------------------------------

def add_hunk_widget(
    parent_layout: QVBoxLayout,
    hunk: Hunk,
    formats: DiffFormats,
    *,
    extra_left_widgets: list[QWidget] | None = None,
    extra_right_widgets: list[QWidget] | None = None,
    on_header_clicked: Callable[[], None] | None = None,
) -> None:
    """Append a header row + sized-to-fit diff editor for one hunk into parent_layout.

    The header row layout is: extra_left_widgets..., colored @@ label, stretch,
    extra_right_widgets... Both lists default to empty.
    Header row is set to HEADER_ROW_HEIGHT.
    The diff editor is sized to exactly fit hunk.lines (no scroll).
    """
    if extra_left_widgets is None:
        extra_left_widgets = []
    if extra_right_widgets is None:
        extra_right_widgets = []

    # --- Header row ---
    header_row = QWidget()
    header_layout = QHBoxLayout(header_row)
    header_layout.setContentsMargins(0, HEADER_ROW_VPAD, 0, HEADER_ROW_VPAD)
    header_layout.setSpacing(4)
    for w in extra_left_widgets:
        header_layout.addWidget(w)
    header_text = hunk.header.strip()
    if on_header_clicked is not None:
        header_label = _ClickableLabel(header_text, on_header_clicked)
    else:
        header_label = QLabel(header_text)
    header_label.setStyleSheet(f"color: {_hunk_header_color()};")
    header_layout.addWidget(header_label)
    header_layout.addStretch()
    for w in extra_right_widgets:
        header_layout.addWidget(w)
    header_row.setFixedHeight(HEADER_ROW_HEIGHT + HEADER_ROW_VPAD * 2)

    # --- Diff editor ---
    editor = make_diff_editor()

    def _render(current_formats: DiffFormats) -> int:
        editor.clear()
        cursor = editor.textCursor()
        count = render_hunk_content_lines(cursor, hunk, current_formats)
        editor.setTextCursor(cursor)
        return count

    line_count = _render(formats)

    line_height = editor.fontMetrics().lineSpacing()
    margins = editor.contentsMargins()
    doc_margin = editor.document().documentMargin() * 2
    total_height = int(line_count * line_height + doc_margin + margins.top() + margins.bottom() + 4)
    editor.setFixedHeight(max(total_height, 4))
    editor.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def _rebuild() -> None:
        header_label.setStyleSheet(f"color: {_hunk_header_color()};")
        _render(make_diff_formats())

    connect_widget(editor, rebuild=_rebuild)

    parent_layout.addWidget(header_row)
    parent_layout.addWidget(editor)


def make_skeleton_container() -> QWidget:
    """Return a QWidget containing 4 gray placeholder bars that mimic diff rows.

    Used as a placeholder inside a file block while the real hunks are being loaded.
    """
    from PySide6.QtWidgets import QVBoxLayout, QFrame
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(8, 6, 8, 6)
    layout.setSpacing(4)
    for width_pct in (90, 60, 75, 50):
        bar = QFrame()
        bar.setFixedHeight(10)
        bar.setMinimumWidth(40)
        bar.setStyleSheet(
            "background-color: rgba(128, 128, 128, 40); border-radius: 3px;"
        )
        layout.addWidget(bar)
    return container
