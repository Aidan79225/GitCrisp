from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QWidget

from git_gui.domain.entities import Commit
from git_gui.presentation.theme import ColorRole, connect_widget, get_theme_manager
from git_gui.presentation.widgets.author_avatar import paint_avatar
from git_gui.presentation.widgets.avatar_loader import get_avatar_loader
from git_gui.presentation.widgets.ref_badge_delegate import (
    BADGE_GAP,
    BADGE_H_PAD,
    BADGE_V_PAD,
    _badge_color,
    _badge_copy_text,
    _badge_display_name,
    paint_badge,
)


def _colour(role: ColorRole) -> QColor:
    return get_theme_manager().current.colors.as_qcolor(role)


PAD = 12
AVATAR_SIZE = 36
AVATAR_GAP = 10
TEXT_LEFT = PAD + AVATAR_SIZE + AVATAR_GAP
AUTHOR_LABEL = "Author: "
COMMIT_LABEL = "Commit: "
PARENT_LABEL = "Parent: "
LINE_COUNT = 3  # author, then the hash with its badges, then the parents


def _line_top(line: int, line_h: int) -> int:
    return PAD + line * (line_h + PAD)


@dataclass(frozen=True)
class _AuthorLine:
    """Line 1 as laid out: the author, cut to end before the timestamp starts."""

    author: str
    author_x: int
    timestamp: str
    timestamp_x: int


@dataclass(frozen=True)
class _Badge:
    rect: QRect
    ref: str  # as the graph names it, which decides the colour
    label: str
    copy_text: str


@dataclass(frozen=True)
class _DetailLayout:
    """Where each part of the header goes, for painting and hit-testing alike."""

    avatar: QRect
    author_top: int
    author_line: _AuthorLine
    cut_author: QRect | None  # the author's slot, when the author had to be cut
    oid: QRect
    badges: tuple[_Badge, ...]
    parents_top: int
    parents_x: int


class CommitDetailWidget(QWidget):
    commit_oid_copy_requested = Signal(str)  # full 40-char OID
    ref_copy_requested = Signal(str)  # branch/tag name

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._commit: Commit | None = None
        self._refs: list[str] = []
        self._head_branch: str | None = None
        self._remote_branches: frozenset[str] = frozenset()
        self._avatar_hash: str | None = None
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
        remote_branches: frozenset[str] = frozenset(),
    ) -> None:
        self._commit = commit
        self._refs = refs
        self._head_branch = head_branch
        self._remote_branches = remote_branches
        self._avatar_hash = self._avatar_loader.hash_for_author(commit.author)
        # Prime the cache; first call may kick off async fetch.
        self._avatar_loader.get_pixmap(commit.author)
        self.setFixedHeight(self.fontMetrics().height() * LINE_COUNT + PAD * (LINE_COUNT + 1))
        self.update()

    def clear(self) -> None:
        self._commit = None
        self._refs = []
        self._avatar_hash = None
        self.update()

    def _on_avatar_ready(self, email_hash: str) -> None:
        if email_hash == self._avatar_hash:
            self.update()

    def paintEvent(self, event) -> None:
        if self._commit is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        layout = self._layout(self._commit, painter.fontMetrics())
        paint_avatar(
            painter,
            layout.avatar,
            self._commit.author,
            self._avatar_loader.get_pixmap(self._commit.author),
        )
        self._paint_author_line(painter, layout)
        self._paint_hash_and_badges(painter, layout, self._commit.oid)
        self._paint_parents(painter, layout, self._commit.parents)
        painter.end()

    def _layout(self, commit: Commit, fm: QFontMetrics) -> _DetailLayout:
        line_h = fm.height()
        author_top, oid_top, parents_top = (_line_top(line, line_h) for line in range(LINE_COUNT))
        author_line = self._author_line(commit, fm)
        author_slot = QRect(
            author_line.author_x, author_top, author_line.timestamp_x - author_line.author_x, line_h
        )
        oid = QRect(
            TEXT_LEFT + fm.horizontalAdvance(COMMIT_LABEL),
            oid_top,
            fm.horizontalAdvance(commit.oid),
            line_h,
        )
        return _DetailLayout(
            avatar=QRect(PAD, (self.height() - AVATAR_SIZE) // 2, AVATAR_SIZE, AVATAR_SIZE),
            author_top=author_top,
            author_line=author_line,
            cut_author=author_slot if author_line.author != commit.author else None,
            oid=oid,
            badges=self._badges(fm, oid.x() + oid.width() + BADGE_GAP * 2, oid_top + line_h // 2),
            parents_top=parents_top,
            parents_x=TEXT_LEFT + fm.horizontalAdvance(PARENT_LABEL),
        )

    def _badges(self, fm: QFontMetrics, x: int, centre_y: int) -> tuple[_Badge, ...]:
        """The ref badges in a row from `x`, centred on the hash's line."""
        badge_h = fm.height() + BADGE_V_PAD * 2
        badges = []
        for ref in self._refs:
            label = _badge_display_name(ref)
            badge_w = fm.horizontalAdvance(label) + BADGE_H_PAD * 2
            rect = QRect(x, centre_y - badge_h // 2, badge_w, badge_h)
            badges.append(_Badge(rect, ref, label, _badge_copy_text(ref)))
            x += badge_w + BADGE_GAP
        return tuple(badges)

    @staticmethod
    def _draw_label(painter: QPainter, top: int, label: str) -> None:
        painter.setPen(_colour(ColorRole.ON_SURFACE_VARIANT))
        painter.drawText(TEXT_LEFT, top + painter.fontMetrics().ascent(), label)

    def _paint_author_line(self, painter: QPainter, layout: _DetailLayout) -> None:
        line = layout.author_line
        baseline = layout.author_top + painter.fontMetrics().ascent()
        self._draw_label(painter, layout.author_top, AUTHOR_LABEL)
        painter.setPen(_colour(ColorRole.ON_SURFACE))
        painter.drawText(line.author_x, baseline, line.author)
        painter.setPen(_colour(ColorRole.ON_SURFACE_VARIANT))
        painter.drawText(line.timestamp_x, baseline, line.timestamp)

    def _paint_hash_and_badges(self, painter: QPainter, layout: _DetailLayout, oid: str) -> None:
        baseline = layout.oid.top() + painter.fontMetrics().ascent()
        self._draw_label(painter, layout.oid.top(), COMMIT_LABEL)
        oid_font = QFont(painter.font())
        oid_font.setUnderline(True)
        painter.setFont(oid_font)
        painter.setPen(_colour(ColorRole.ON_SURFACE))
        painter.drawText(layout.oid.x(), baseline, oid)
        oid_font.setUnderline(False)
        painter.setFont(oid_font)
        for badge in layout.badges:
            self._paint_badge(painter, badge)

    def _paint_badge(self, painter: QPainter, badge: _Badge) -> None:
        fill = _badge_color(badge.ref, self._head_branch, self._remote_branches)
        paint_badge(painter, badge.rect, fill, badge.label)

    def _paint_parents(self, painter: QPainter, layout: _DetailLayout, parents: list[str]) -> None:
        baseline = layout.parents_top + painter.fontMetrics().ascent()
        self._draw_label(painter, layout.parents_top, PARENT_LABEL)
        painter.setPen(_colour(ColorRole.ON_SURFACE))
        painter.drawText(layout.parents_x, baseline, "  ".join(parents) if parents else "(none)")

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
        if self._commit is None:
            return ""
        cut = self._layout(self._commit, self.fontMetrics()).cut_author
        return self._commit.author if cut is not None and cut.contains(pos) else ""

    def _copyable_at(self, pos) -> str | None:
        """Return the text to copy if a clickable element is under `pos`."""
        if self._commit is None:
            return None
        layout = self._layout(self._commit, self.fontMetrics())
        if layout.oid.contains(pos):
            return self._commit.oid
        return next((badge.copy_text for badge in layout.badges if badge.rect.contains(pos)), None)

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
            layout = self._layout(self._commit, self.fontMetrics())
            if layout.oid.contains(pos):
                self.commit_oid_copy_requested.emit(self._commit.oid)
                event.accept()
                return
            for badge in layout.badges:
                if badge.rect.contains(pos):
                    self.ref_copy_requested.emit(badge.copy_text)
                    event.accept()
                    return
        super().mousePressEvent(event)
