# git_gui/presentation/widgets/commit_detail.py
from __future__ import annotations
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QBrush, QColor, QPainter
from PySide6.QtWidgets import QWidget
from git_gui.domain.entities import Commit
from git_gui.presentation.theme import get_theme_manager, connect_widget
from git_gui.presentation.widgets.ref_badge_delegate import (
    _badge_color, _badge_display_name, BADGE_RADIUS, BADGE_H_PAD, BADGE_V_PAD, BADGE_GAP,
)


def _muted() -> QColor:
    return get_theme_manager().current.colors.as_qcolor("on_surface_variant")


PAD = 8


class CommitDetailWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._commit: Commit | None = None
        self._refs: list[str] = []
        connect_widget(self)

    def set_commit(self, commit: Commit, refs: list[str]) -> None:
        self._commit = commit
        self._refs = refs
        fm = self.fontMetrics()
        self.setFixedHeight(fm.height() * 3 + PAD * 4)
        self.update()

    def clear(self) -> None:
        self._commit = None
        self._refs = []
        self.update()

    def paintEvent(self, event) -> None:
        if self._commit is None:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        fm = painter.fontMetrics()
        line_h = fm.height()
        w = self.width()
        c = self._commit
        on_surface = get_theme_manager().current.colors.as_qcolor("on_surface")
        on_badge = get_theme_manager().current.colors.as_qcolor("on_badge")

        # ── Line 1: Author + datetime ────────────────────────────────────────
        y = PAD
        painter.setPen(_muted())
        painter.drawText(PAD, y + fm.ascent(), "Author: ")
        label_w = fm.horizontalAdvance("Author: ")
        painter.setPen(on_surface)
        painter.drawText(PAD + label_w, y + fm.ascent(), c.author)
        ts = c.timestamp.strftime("%Y-%m-%d %H:%M")
        ts_w = fm.horizontalAdvance(ts)
        painter.setPen(_muted())
        painter.drawText(w - PAD - ts_w, y + fm.ascent(), ts)

        # ── Line 2: Hash + ref badges ────────────────────────────────────────
        y += line_h + PAD
        painter.setPen(_muted())
        painter.drawText(PAD, y + fm.ascent(), "Commit: ")
        x = PAD + fm.horizontalAdvance("Commit: ")
        painter.setPen(on_surface)
        painter.drawText(x, y + fm.ascent(), c.oid)
        x += fm.horizontalAdvance(c.oid) + BADGE_GAP * 2

        badge_h = line_h + BADGE_V_PAD * 2
        cy = y + line_h // 2
        for name in self._refs:
            display = _badge_display_name(name)
            badge_w = fm.horizontalAdvance(display) + BADGE_H_PAD * 2
            badge_rect = QRect(x, cy - badge_h // 2, badge_w, badge_h)
            painter.setBrush(QBrush(_badge_color(name)))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(badge_rect, BADGE_RADIUS, BADGE_RADIUS)
            painter.setPen(on_badge)
            painter.drawText(badge_rect, Qt.AlignCenter, display)
            x += badge_w + BADGE_GAP

        # ── Line 3: Parent(s) ────────────────────────────────────────────────
        y += line_h + PAD
        painter.setPen(_muted())
        painter.drawText(PAD, y + fm.ascent(), "Parent: ")
        x = PAD + fm.horizontalAdvance("Parent: ")
        painter.setPen(on_surface)
        parents_text = "  ".join(c.parents) if c.parents else "(none)"
        painter.drawText(x, y + fm.ascent(), parents_text)

        painter.end()
