# git_gui/presentation/widgets/diff_block.py
"""Shared helpers for rendering diff hunks in both commit-detail and working-tree views."""
from __future__ import annotations

import re
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextBlockFormat, QTextCharFormat
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from git_gui.domain.entities import Hunk

# ---------------------------------------------------------------------------
# Style constants
# ---------------------------------------------------------------------------

FILE_BLOCK_STYLE = (
    "QFrame#fileBlock { border: 1px solid #30363d; border-radius: 4px; background-color: #161b22; }"
)
HEADER_STYLE = "color: #e3b341; font-weight: bold;"
HUNK_HEADER_COLOR = "#58a6ff"
HEADER_ROW_HEIGHT = 24  # consistent height for file + hunk header rows


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
    frame.setStyleSheet(FILE_BLOCK_STYLE)
    inner = QVBoxLayout(frame)
    inner.setContentsMargins(8, 8, 8, 8)
    inner.setSpacing(4)

    # Wrap the header label in a row container so its layout matches the
    # hunk header rows below — keeps heights consistent.
    header_row = QWidget()
    header_row_layout = QHBoxLayout(header_row)
    header_row_layout.setContentsMargins(0, 0, 0, 0)
    header_label = QLabel(f"\U0001f4c4 {path}")
    header_label.setStyleSheet(HEADER_STYLE)
    header_row_layout.addWidget(header_label)
    header_row_layout.addStretch()
    header_row.setFixedHeight(HEADER_ROW_HEIGHT)
    inner.addWidget(header_row)

    return frame, inner


def make_diff_formats() -> DiffFormats:
    """Return a DiffFormats dataclass with all QTextCharFormat / QTextBlockFormat objects."""
    fmt_added = QTextCharFormat()
    fmt_added.setForeground(QColor("white"))

    fmt_removed = QTextCharFormat()
    fmt_removed.setForeground(QColor("white"))

    fmt_header = QTextCharFormat()
    fmt_header.setForeground(QColor(HUNK_HEADER_COLOR))

    fmt_default = QTextCharFormat()
    fmt_default.setForeground(QColor("white"))

    blk_added = QTextBlockFormat()
    blk_added.setBackground(QColor(35, 134, 54, 80))

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
