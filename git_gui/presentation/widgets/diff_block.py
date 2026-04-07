# git_gui/presentation/widgets/diff_block.py
"""Shared helpers for rendering diff hunks in both commit-detail and working-tree views."""
from __future__ import annotations

import re
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextBlockFormat, QTextCharFormat
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QSizePolicy, QVBoxLayout, QWidget,
)

from git_gui.domain.entities import Hunk
from git_gui.presentation.theme import get_theme_manager

# ---------------------------------------------------------------------------
# Style constants
# ---------------------------------------------------------------------------

def _file_block_style() -> str:
    c = get_theme_manager().current.colors
    return (
        f"QFrame#fileBlock {{ border: 1px solid {c.outline}; "
        f"border-radius: 4px; background-color: {c.surface_container_high}; }}"
    )

# TODO(theme): #e3b341 is a yellow accent with no clean MD3 token mapping.
HEADER_STYLE = "color: #e3b341; font-weight: bold;"
# TODO(theme): #58a6ff is a domain blue accent with no clean MD3 token mapping.
HUNK_HEADER_COLOR = "#58a6ff"
HEADER_ROW_HEIGHT = 22  # consistent height for file + hunk header rows
HEADER_ROW_VPAD = 3      # top/bottom padding inside the header row


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


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def make_file_block(path: str) -> tuple[QFrame, QVBoxLayout]:
    """Return a bordered QFrame with an amber file-header label and its inner layout."""
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
    header_label = QLabel(f"\U0001f4c4 {path}")
    header_label.setStyleSheet(HEADER_STYLE)
    header_row_layout.addWidget(header_label)
    header_row_layout.addStretch()
    header_row.setFixedHeight(HEADER_ROW_HEIGHT + HEADER_ROW_VPAD * 2)
    inner.addWidget(header_row)

    return frame, inner


def make_diff_formats() -> DiffFormats:
    """Return a DiffFormats dataclass with all QTextCharFormat / QTextBlockFormat objects."""
    # TODO(theme): "white" foreground — no clean on-surface token swap without visual change.
    fmt_added = QTextCharFormat()
    fmt_added.setForeground(QColor("white"))

    # TODO(theme): "white" foreground — no clean on-surface token swap without visual change.
    fmt_removed = QTextCharFormat()
    fmt_removed.setForeground(QColor("white"))

    fmt_header = QTextCharFormat()
    fmt_header.setForeground(QColor(HUNK_HEADER_COLOR))

    # TODO(theme): "white" foreground — no clean on-surface token swap without visual change.
    fmt_default = QTextCharFormat()
    fmt_default.setForeground(QColor("white"))

    # TODO(theme): semi-transparent green over surface_container_high; preserve exact look.
    blk_added = QTextBlockFormat()
    blk_added.setBackground(QColor(35, 134, 54, 80))

    # TODO(theme): semi-transparent red over surface_container_high; preserve exact look.
    blk_removed = QTextBlockFormat()
    blk_removed.setBackground(QColor(248, 81, 73, 80))

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


def make_diff_editor() -> QPlainTextEdit:
    """Return a configured read-only no-wrap monospace QPlainTextEdit for diff display."""
    editor = QPlainTextEdit()
    editor.setReadOnly(True)
    editor.setLineWrapMode(QPlainTextEdit.NoWrap)
    editor.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    font = editor.font()
    font.setFamily("Courier New")
    editor.setFont(font)
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


def render_hunk_content_lines(cursor, hunk: Hunk, formats: DiffFormats) -> int:
    """Insert the +/-/context lines of *hunk* into *cursor*.

    Returns the number of lines inserted (== len(hunk.lines)).
    Zero-line hunks are a no-op returning 0.
    """
    if not hunk.lines:
        return 0

    old_line, new_line = parse_hunk_header(hunk.header)
    for origin, content in hunk.lines:
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
        line = content if content.endswith("\n") else content + "\n"
        cursor.insertText(prefix + line)

    return len(hunk.lines)


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
    header_label = QLabel(hunk.header.strip())
    header_label.setStyleSheet(f"color: {HUNK_HEADER_COLOR};")
    header_layout.addWidget(header_label)
    header_layout.addStretch()
    for w in extra_right_widgets:
        header_layout.addWidget(w)
    header_row.setFixedHeight(HEADER_ROW_HEIGHT + HEADER_ROW_VPAD * 2)

    # --- Diff editor ---
    editor = make_diff_editor()
    cursor = editor.textCursor()
    line_count = render_hunk_content_lines(cursor, hunk, formats)
    editor.setTextCursor(cursor)

    line_height = editor.fontMetrics().lineSpacing()
    margins = editor.contentsMargins()
    doc_margin = editor.document().documentMargin() * 2
    total_height = int(line_count * line_height + doc_margin + margins.top() + margins.bottom() + 4)
    editor.setFixedHeight(max(total_height, 4))
    editor.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    parent_layout.addWidget(header_row)
    parent_layout.addWidget(editor)
