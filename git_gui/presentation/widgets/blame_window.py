# git_gui/presentation/widgets/blame_window.py
"""Blame view — a file's lines beside the commit that last touched each one.

A window of its own rather than a pane inside the main one: the point of blame
is to pick a line and see the commit behind it, and the main window needs its
commit list and diff pane free to answer that.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from git_gui.domain.entities import BlameLine
from git_gui.presentation.bus import QueryBus
from git_gui.presentation.theme import connect_widget, get_theme_manager
from git_gui.presentation.widgets.diff_block import (
    _KIND_TO_ATTR,
    make_diff_editor,
    make_syntax_formats,
)
from git_gui.presentation.widgets.syntax_highlighter import tokenize

SHA_CHARS = 8
AUTHOR_CHARS = 14  # author names are truncated to keep the gutter a fixed width
STRIPE_W = 5  # commit colour bar down the left of the gutter
GUTTER_PAD = 8
COL_GAP = 10


def _lane_color(oid: str) -> QColor:
    """A stable colour per commit, from the same palette the graph lanes use.

    Sharing the palette means a commit that is, say, purple in a blame gutter
    reads as the same kind of thing as a purple lane — one colour vocabulary
    rather than two.
    """
    colors = get_theme_manager().current.colors.graph_lane_colors
    return QColor(colors[int(oid[:8], 16) % len(colors)])


def _elide(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


class _LoadSignals(QObject):
    done = Signal(list, str, str)  # lines, path, oid
    failed = Signal(str)


class _Gutter(QWidget):
    """Blame column painted alongside the editor, one entry per text block."""

    def __init__(self, editor: _BlameEditor) -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.gutter_width(), 0)

    def paintEvent(self, event) -> None:
        self._editor.paint_gutter(event)

    def mousePressEvent(self, event) -> None:
        self._editor.select_line_at(event.position().toPoint().y())

    def contextMenuEvent(self, event) -> None:
        self._editor.select_line_at(event.pos().y())
        self._editor.gutter_context_menu.emit(event.globalPos())


class _BlameEditor(QPlainTextEdit):
    """Read-only code view with a blame gutter down its left edge."""

    gutter_context_menu = Signal(object)  # QPoint, in global coordinates

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        base = make_diff_editor()
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setStyleSheet(base.styleSheet())
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self._lines: list[BlameLine] = []
        self._path = ""  # kept so a theme change can re-tokenize in place
        self._gutter = _Gutter(self)

        self.blockCountChanged.connect(lambda _: self._sync_gutter_width())
        self.updateRequest.connect(self._on_update_request)
        self._sync_gutter_width()

    # ── content ──────────────────────────────────────────────────────────────

    def set_lines(self, lines: list[BlameLine], path: str) -> None:
        self._lines = lines
        self._path = path
        self.setPlainText("\n".join(line.text for line in lines))
        self._apply_syntax(path)
        self._sync_gutter_width()
        self._gutter.update()

    def line_at_block(self, block_number: int) -> BlameLine | None:
        if 0 <= block_number < len(self._lines):
            return self._lines[block_number]
        return None

    def current_line(self) -> BlameLine | None:
        return self.line_at_block(self.textCursor().blockNumber())

    def restyle(self) -> None:
        """Re-colour for the active theme.

        Syntax colours are baked into the document's char formats when the file
        loads, so a repaint alone would leave the previous theme's palette in
        place — light-theme token colours on a dark surface are unreadable.
        Merging the new formats over the same ranges fixes them without
        disturbing the text, the cursor, or the scroll position.
        """
        self._apply_syntax(self._path)
        self._gutter.update()

    def _apply_syntax(self, path: str) -> None:
        formats = make_syntax_formats()
        document = self.document()
        for token in tokenize(self.toPlainText(), path):
            attr = _KIND_TO_ATTR.get(token.kind)
            if attr is None:
                continue
            cursor = QTextCursor(document)
            cursor.setPosition(token.start)
            cursor.setPosition(token.end, QTextCursor.KeepAnchor)
            cursor.mergeCharFormat(getattr(formats, attr))

    # ── gutter geometry ──────────────────────────────────────────────────────

    def gutter_width(self) -> int:
        fm = QFontMetrics(self.font())
        digits = max(len(str(len(self._lines))), 3)
        return (
            STRIPE_W
            + GUTTER_PAD
            + fm.horizontalAdvance("0" * SHA_CHARS)
            + COL_GAP
            + fm.horizontalAdvance("W" * AUTHOR_CHARS)
            + COL_GAP
            + fm.horizontalAdvance("2026-01-01")
            + COL_GAP
            + fm.horizontalAdvance("9" * digits)
            + GUTTER_PAD
        )

    def _sync_gutter_width(self) -> None:
        width = self.gutter_width()
        self.setViewportMargins(width, 0, 0, 0)
        self._gutter.setFixedWidth(width)

    def _on_update_request(self, rect: QRect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def select_line_at_block(self, block_number: int) -> None:
        """Put the cursor on a line by index, as a gutter click or a test would."""
        block = self.document().findBlockByNumber(block_number)
        if not block.isValid():
            return
        cursor = self.textCursor()
        cursor.setPosition(block.position())
        self.setTextCursor(cursor)

    def select_line_at(self, y: int) -> None:
        """Put the cursor on the line the gutter was clicked next to."""
        block = self.firstVisibleBlock()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        while block.isValid():
            bottom = top + self.blockBoundingRect(block).height()
            if top <= y < bottom:
                self.select_line_at_block(block.blockNumber())
                return
            block = block.next()
            top = bottom

    # ── gutter painting ──────────────────────────────────────────────────────

    def paint_gutter(self, event) -> None:
        colors = get_theme_manager().current.colors
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), colors.as_qcolor("surface_container"))

        fm = QFontMetrics(self.font())
        muted = colors.as_qcolor("on_surface_variant")
        strong = colors.as_qcolor("on_surface")
        divider = colors.as_qcolor("outline_variant")
        width = self._gutter.width()

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())

        while block.isValid() and top <= event.rect().bottom():
            line = self.line_at_block(block_number)
            if block.isVisible() and bottom >= event.rect().top() and line is not None:
                height = bottom - top
                painter.fillRect(0, top, STRIPE_W, height, _lane_color(line.commit_oid))

                x = STRIPE_W + GUTTER_PAD
                # Attribution is written once per run of lines from one commit;
                # repeating it on every line drowns the code in metadata.
                if line.is_run_start:
                    if block_number:
                        painter.setPen(divider)
                        painter.drawLine(STRIPE_W, top, width, top)
                    painter.setPen(strong)
                    painter.drawText(
                        x, top, width, height, Qt.AlignVCenter, line.commit_oid[:SHA_CHARS]
                    )
                    x += fm.horizontalAdvance("0" * SHA_CHARS) + COL_GAP
                    painter.setPen(muted)
                    painter.drawText(
                        x, top, width, height, Qt.AlignVCenter, _elide(line.author, AUTHOR_CHARS)
                    )
                    x += fm.horizontalAdvance("W" * AUTHOR_CHARS) + COL_GAP
                    painter.drawText(
                        x, top, width, height, Qt.AlignVCenter, f"{line.timestamp:%Y-%m-%d}"
                    )

                painter.setPen(muted)
                painter.drawText(
                    0,
                    top,
                    width - GUTTER_PAD,
                    height,
                    Qt.AlignVCenter | Qt.AlignRight,
                    str(line.line_no),
                )

            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1


class BlameWindow(QWidget):
    """Non-modal blame view for one file at one revision."""

    commit_selected = Signal(str)  # oid of the commit behind the current line

    def __init__(self, queries: QueryBus, path: str, at_oid: str | None = None, parent=None):
        super().__init__(parent)
        self._queries = queries
        self._path = path
        self._oid = at_oid
        # Revisions walked back through with "Blame before this commit", so the
        # trail back out of an archaeology dig is never lost.
        self._history: list[tuple[str, str | None]] = []
        self._last_emitted: str | None = None
        # Loading content moves the cursor; that is not the user picking a line.
        self._suppress_emit = False
        self._load_signals: _LoadSignals | None = None

        self._back_btn = QPushButton("← Back")
        self._back_btn.setEnabled(False)
        self._back_btn.clicked.connect(self._go_back)

        self._status = QLabel()
        self._status.setTextInteractionFlags(Qt.TextSelectableByMouse)

        header = QHBoxLayout()
        header.setContentsMargins(8, 6, 8, 6)
        header.addWidget(self._back_btn)
        header.addWidget(self._status, 1)

        self._editor = _BlameEditor()
        self._editor.cursorPositionChanged.connect(self._on_cursor_moved)
        self._editor.gutter_context_menu.connect(self._show_gutter_menu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addWidget(self._editor, 1)

        self.resize(1000, 700)
        connect_widget(self, rebuild=self._editor.restyle)
        self._reload()

    # ── loading ──────────────────────────────────────────────────────────────

    def _reload(self) -> None:
        path, oid = self._path, self._oid
        self._back_btn.setEnabled(bool(self._history))
        self._set_title(loading=True)

        signals = _LoadSignals()
        signals.done.connect(self._on_loaded)
        signals.failed.connect(self._on_failed)
        self._load_signals = signals  # prevent GC while the worker runs

        queries = self._queries

        def _worker() -> None:
            try:
                lines = queries.get_blame.execute(path, at_oid=oid)
            except Exception as e:  # surfaced in the header, not swallowed
                signals.failed.emit(str(e))
                return
            signals.done.emit(lines, path, oid or "")

        threading.Thread(target=_worker, daemon=True).start()

    def _on_loaded(self, lines: list[BlameLine], path: str, oid: str) -> None:
        if (path, oid or None) != (self._path, self._oid):
            return  # the user moved on while this was in flight
        self._suppress_emit = True
        self._editor.set_lines(lines, path)
        self._suppress_emit = False
        # The cursor now sits on line 1; record its commit as already current so
        # opening blame never yanks the main window's selection on its own.
        self._last_emitted = lines[0].commit_oid if lines else None
        self._set_title()

    def _on_failed(self, message: str) -> None:
        self._editor.set_lines([], self._path)
        self._status.setText(message)
        self.setWindowTitle(f"Blame — {self._path}")

    def _set_title(self, *, loading: bool = False) -> None:
        rev = self._oid[:SHA_CHARS] if self._oid else "HEAD"
        self.setWindowTitle(f"Blame — {self._path} @ {rev}")
        self._status.setText(f"Blaming {self._path} …" if loading else f"{self._path} @ {rev}")

    # ── navigation ───────────────────────────────────────────────────────────

    def _on_cursor_moved(self) -> None:
        if self._suppress_emit:
            return
        line = self._editor.current_line()
        if line is None or line.commit_oid == self._last_emitted:
            return
        self._last_emitted = line.commit_oid
        self.commit_selected.emit(line.commit_oid)

    def _show_gutter_menu(self, global_pos) -> None:
        line = self._editor.current_line()
        if line is None:
            return
        menu = QMenu(self)
        before = menu.addAction(f"Blame before {line.commit_oid[:SHA_CHARS]}")
        if menu.exec(global_pos) is before:
            self._blame_before(line.commit_oid)

    def _blame_before(self, oid: str) -> None:
        """Re-blame at the parent of `oid` — the state the file was in before it."""
        try:
            parents = self._queries.get_commit_detail.execute(oid).parents
        except Exception as e:
            self._status.setText(str(e))
            return
        if not parents:
            # A root commit, or a graft boundary in a shallow clone — either way
            # there is no earlier revision here to blame.
            self._status.setText(
                f"{oid[:SHA_CHARS]} has no parent in this repository — nothing earlier to blame."
            )
            return
        self._history.append((self._path, self._oid))
        self._oid = parents[0]
        self._reload()

    def _go_back(self) -> None:
        if not self._history:
            return
        self._path, self._oid = self._history.pop()
        self._reload()
