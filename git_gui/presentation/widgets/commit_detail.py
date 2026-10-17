from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QRect, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QWidget

from git_gui.domain.entities import Commit
from git_gui.presentation.theme import ColorRole, connect_widget, get_theme_manager
from git_gui.presentation.widgets.author_avatar import paint_avatar
from git_gui.presentation.widgets.avatar_loader import get_avatar_loader
from git_gui.presentation.widgets.ref_badge_delegate import (
    BADGE_GAP,
    BADGE_H_PAD,
    BADGE_RADIUS,
    BADGE_V_PAD,
    _badge_color,
    _badge_copy_text,
    _badge_display_name,
)


def _muted() -> QColor:
    return get_theme_manager().current.colors.as_qcolor(ColorRole.ON_SURFACE_VARIANT)


PAD = 12
AVATAR_SIZE = 36
AVATAR_GAP = 10
TEXT_LEFT = PAD + AVATAR_SIZE + AVATAR_GAP
AUTHOR_LABEL = "Author: "


@dataclass(frozen=True)
class _AuthorLine:
    """Line 1 as laid out: the author, cut to end before the timestamp starts."""

    author: str
    author_x: int
    timestamp: str
    timestamp_x: int


class CommitDetailWidget(QWidget):
    commit_oid_copy_requested = Signal(str)  # full 40-char OID
    ref_copy_requested = Signal(str)  # branch/tag name

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._commit: Commit | None = None
        self._refs: list[str] = []
        self._head_branch: str | None = None
        self._remote_branches: frozenset[str] | None = None
        self._avatar_hash: str | None = None
        self._oid_rect: QRect | None = None
        self._cut_author_rect: QRect | None = None
        # Clickable ref badges painted on line 2: (rect, copy text).
        self._badge_rects: list[tuple[QRect, str]] = []
        self.setMouseTracking(True)
        connect_widget(self)
        self._avatar_loader = get_avatar_loader()
        self._avatar_loader.avatar_ready.connect(self._on_avatar_ready)
        self._avatar_loader.enabled_changed.connect(lambda _v: self.update())

    def set_commit(
        self,
        commit: Commit,
        refs: list[str],
        *,
        head_branch: str | None = None,
        remote_branches: frozenset[str] | None = None,
    ) -> None:
        self._commit = commit
        self._refs = refs
        self._head_branch = head_branch
        self._remote_branches = remote_branches
        self._avatar_hash = self._avatar_loader.hash_for_author(commit.author)
        # Prime the cache; first call may kick off async fetch.
        self._avatar_loader.get_pixmap(commit.author)
        fm = self.fontMetrics()
        self.setFixedHeight(fm.height() * 3 + PAD * 4)
        self.update()

    def clear(self) -> None:
        self._commit = None
        self._refs = []
        self._avatar_hash = None
        self._oid_rect = None
        self._cut_author_rect = None
        self._badge_rects = []
        self.update()

    def _on_avatar_ready(self, email_hash: str) -> None:
        if email_hash == self._avatar_hash:
            self.update()

    def paintEvent(self, event) -> None:
        if self._commit is None:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        fm = painter.fontMetrics()
        line_h = fm.height()
        c = self._commit
        on_surface = get_theme_manager().current.colors.as_qcolor(ColorRole.ON_SURFACE)
        on_badge = get_theme_manager().current.colors.as_qcolor(ColorRole.ON_BADGE)

        # ── Avatar (left, vertically centered) ───────────────────────────────
        avatar_y = (self.height() - AVATAR_SIZE) // 2
        avatar_rect = QRect(PAD, avatar_y, AVATAR_SIZE, AVATAR_SIZE)
        pixmap = self._avatar_loader.get_pixmap(c.author)
        paint_avatar(painter, avatar_rect, c.author, pixmap)
        text_left = TEXT_LEFT

        # ── Line 1: Author + datetime ────────────────────────────────────────
        y = PAD
        line1 = self._author_line(c, fm)
        painter.setPen(_muted())
        painter.drawText(text_left, y + fm.ascent(), AUTHOR_LABEL)
        painter.setPen(on_surface)
        painter.drawText(line1.author_x, y + fm.ascent(), line1.author)
        painter.setPen(_muted())
        painter.drawText(line1.timestamp_x, y + fm.ascent(), line1.timestamp)
        author_slot = QRect(line1.author_x, y, line1.timestamp_x - line1.author_x, line_h)
        self._cut_author_rect = author_slot if line1.author != c.author else None

        # ── Line 2: Hash + ref badges ────────────────────────────────────────
        y += line_h + PAD
        painter.setPen(_muted())
        painter.drawText(text_left, y + fm.ascent(), "Commit: ")
        x = text_left + fm.horizontalAdvance("Commit: ")
        oid_font = QFont(painter.font())
        oid_font.setUnderline(True)
        painter.setFont(oid_font)
        painter.setPen(on_surface)
        painter.drawText(x, y + fm.ascent(), c.oid)
        oid_w = fm.horizontalAdvance(c.oid)
        self._oid_rect = QRect(x, y, oid_w, line_h)
        # Restore the default font for whatever follows on this line.
        oid_font.setUnderline(False)
        painter.setFont(oid_font)
        x += oid_w + BADGE_GAP * 2

        badge_h = line_h + BADGE_V_PAD * 2
        cy = y + line_h // 2
        self._badge_rects = []
        for name in self._refs:
            display = _badge_display_name(name)
            badge_w = fm.horizontalAdvance(display) + BADGE_H_PAD * 2
            badge_rect = QRect(x, cy - badge_h // 2, badge_w, badge_h)
            painter.setBrush(QBrush(_badge_color(name, self._head_branch, self._remote_branches)))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(badge_rect, BADGE_RADIUS, BADGE_RADIUS)
            painter.setPen(on_badge)
            painter.drawText(badge_rect, Qt.AlignCenter, display)
            self._badge_rects.append((badge_rect, _badge_copy_text(name)))
            x += badge_w + BADGE_GAP

        # ── Line 3: Parent(s) ────────────────────────────────────────────────
        y += line_h + PAD
        painter.setPen(_muted())
        painter.drawText(text_left, y + fm.ascent(), "Parent: ")
        x = text_left + fm.horizontalAdvance("Parent: ")
        painter.setPen(on_surface)
        parents_text = "  ".join(c.parents) if c.parents else "(none)"
        painter.drawText(x, y + fm.ascent(), parents_text)

        painter.end()

    def _author_line(self, commit: Commit, fm: QFontMetrics) -> _AuthorLine:
        """Line 1's layout, with the timestamp's place taken first.

        "Name <email>" is often wider than a diff pane beside blame or the
        reflog, so the author is what gives way.
        """
        timestamp = commit.timestamp.strftime("%Y-%m-%d %H:%M")
        timestamp_x = self.width() - PAD - fm.horizontalAdvance(timestamp)
        author_x = TEXT_LEFT + fm.horizontalAdvance(AUTHOR_LABEL)
        room = max(timestamp_x - PAD - author_x, 0)
        author = fm.elidedText(commit.author, Qt.ElideRight, room)
        return _AuthorLine(author, author_x, timestamp, timestamp_x)

    def event(self, event) -> bool:
        if event.type() == QEvent.ToolTip:
            self.setToolTip(self._tooltip_at(event.pos()))
        return super().event(event)

    def _tooltip_at(self, pos) -> str:
        """The whole author, over an author that had to be cut to fit."""
        rect = self._cut_author_rect
        if self._commit is not None and rect is not None and rect.contains(pos):
            return self._commit.author
        return ""

    def _copyable_at(self, pos) -> str | None:
        """Return the text to copy if a clickable element is under `pos`."""
        if self._commit is not None and self._oid_rect is not None and self._oid_rect.contains(pos):
            return self._commit.oid
        for rect, text in self._badge_rects:
            if rect.contains(pos):
                return text
        return None

    def mouseMoveEvent(self, event) -> None:
        pos = event.position().toPoint()
        if self._copyable_at(pos) is not None:
            self.setCursor(Qt.PointingHandCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self.setCursor(Qt.ArrowCursor)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        pos = event.position().toPoint()
        if event.button() == Qt.LeftButton and self._commit is not None:
            if self._oid_rect is not None and self._oid_rect.contains(pos):
                self.commit_oid_copy_requested.emit(self._commit.oid)
                event.accept()
                return
            for rect, text in self._badge_rects:
                if rect.contains(pos):
                    self.ref_copy_requested.emit(text)
                    event.accept()
                    return
        super().mousePressEvent(event)
