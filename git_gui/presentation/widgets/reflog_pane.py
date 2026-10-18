"""Reflog view — where HEAD has been, and what moved it there.

Like blame, this is an index rather than an answer: you scan it for a state
worth going back to, and what you want next is to see what that state was. So
it sits in the commit list's column beside the diff pane, and hands a commit
over the moment a row is picked.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from git_gui.domain.entities import ReflogEntry
from git_gui.presentation.bus import QueryBus
from git_gui.presentation.theme import ColorRole, connect_widget, get_theme_manager
from git_gui.presentation.widgets.eliding_label import ElidingLabel

ENTRY_ROLE = Qt.UserRole + 1  # ReflogEntry for the row

SHA_CHARS = 8
ROW_PAD = 6
META_GAP = 2  # between a row's two lines
META_SCALE = 0.85  # the metadata line reads as secondary to the summary
ORPHAN_STRIPE_W = 4  # marks the entries only the reflog can still reach
ORPHAN_TINT_ALPHA = 38  # a wash over the row, enough to catch a scan
COL_GAP = 10
CHIP_H_PAD = 6
CHIP_RADIUS = 4

# What each operation did, coarsely, so a scan can find the destructive ones.
# Keyed by the word before any qualifier: "commit (amend)" reads as "commit".
#
# Every role here keeps its hue across both themes, which is the point — a
# colour that means "moved the branch" has to mean that in either. status_modified
# is deliberately not used: it is amber in light and blue in dark, so checkout
# would have been near-indistinguishable from reset on the light theme.
_OPERATION_ROLES: dict[str, ColorRole] = {
    "commit": ColorRole.STATUS_ADDED,  # green
    "merge": ColorRole.STATUS_ADDED,
    "reset": ColorRole.STATUS_RENAMED,  # orange — the ones worth finding in a hurry
    "rebase": ColorRole.STATUS_RENAMED,
    "checkout": ColorRole.REF_BADGE_BRANCH_BG,  # blue
    "branch": ColorRole.REF_BADGE_BRANCH_BG,
    "pull": ColorRole.REF_BADGE_BRANCH_BG,
    "clone": ColorRole.REF_BADGE_BRANCH_BG,
    "cherry-pick": ColorRole.REF_BADGE_TAG_BG,  # purple
    "revert": ColorRole.REF_BADGE_TAG_BG,
}


def _operation_color(operation: str) -> QColor:
    colors = get_theme_manager().current.colors
    head = operation.split(" ")[0].split(":")[0].lower()
    return colors.as_qcolor(_OPERATION_ROLES.get(head, ColorRole.STATUS_UNKNOWN))


def _went_nowhere(entry: ReflogEntry) -> bool:
    """True when the ref ended up exactly where it started.

    Restoring to such an entry would put the ref where it already is, so it
    offers nothing to someone looking for a state to get back to. Filtering by
    operation type instead would be a worse cut: most checkouts move HEAD to a
    different commit, and those are perfectly good states to return to.
    """
    return entry.oid_old is not None and entry.oid_old == entry.oid_new


def _movement(entry: ReflogEntry) -> tuple:
    """What identifies one movement from one reload to the next.

    Not its index: each new movement renumbers every entry before it.
    """
    return (entry.oid_old, entry.oid_new, entry.timestamp, entry.operation, entry.summary)


class ReflogModel(QAbstractTableModel):
    """One column per row; the whole row is painted by ReflogDelegate."""

    def __init__(self, entries: list[ReflogEntry] | None = None, parent=None) -> None:
        super().__init__(parent)
        self._all: list[ReflogEntry] = entries or []
        self._show_all = False
        self._entries: list[ReflogEntry] = self._visible()

    def _visible(self) -> list[ReflogEntry]:
        if self._show_all:
            return list(self._all)
        # An orphan is never hidden whatever it did: reaching those is the one
        # thing nothing else in the app can do.
        return [e for e in self._all if e.is_orphaned or not _went_nowhere(e)]

    def hidden_count(self) -> int:
        return len(self._all) - len(self._entries)

    def set_show_all(self, show_all: bool) -> None:
        if show_all == self._show_all:
            return
        self.beginResetModel()
        self._show_all = show_all
        self._entries = self._visible()
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._entries)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 1

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._entries):
            return None
        entry = self._entries[index.row()]
        if role == Qt.DisplayRole:
            return ""  # the row is fully painted by the delegate
        if role == ENTRY_ROLE:
            return entry
        if role == Qt.ToolTipRole:
            # The sha and the date are on the row now; the committer is not.
            base = f"By {entry.committer}" if entry.committer else ""
            if not entry.is_orphaned:
                return base or None
            orphan_note = (
                "No branch or tag reaches this commit any more — the reflog is "
                "the only way back to it, and it will be collected once this "
                "entry expires."
            )
            return f"{base}\n\n{orphan_note}" if base else orphan_note
        return None

    def widest_operation(self, fm) -> int:
        """Width of the widest operation label present.

        The chips vary in width, so without a common column the summaries
        start at a different x on every row — which is exactly what a scan
        down the list has to fight.
        """
        labels = {e.operation or "—" for e in self._entries}
        return max((fm.horizontalAdvance(label) for label in labels), default=0)

    def entry_at(self, row: int) -> ReflogEntry | None:
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def row_of(self, entry: ReflogEntry) -> int | None:
        """The row showing the same movement as `entry`, if one does."""
        wanted = _movement(entry)
        return next((row for row, e in enumerate(self._entries) if _movement(e) == wanted), None)

    def reload(self, entries: list[ReflogEntry]) -> None:
        self.beginResetModel()
        self._all = entries
        self._entries = self._visible()
        self.endResetModel()


def _meta_font(base: QFont) -> QFont:
    font = QFont(base)
    font.setPointSizeF(max(1.0, base.pointSizeF() * META_SCALE))
    return font


class ReflogDelegate(QStyledItemDelegate):
    """Two lines per entry: what happened, then where and when.

    It was one line, with the position, sha and date each holding a column of
    their own — 381px of a row spoken for before the summary got any. In a
    pane that shares its width with the diff, that came straight out of the
    diff. Stacking the three onto a second line costs a row of height and
    hands the width back, and it puts the summary next to the operation chip
    that qualifies it, which is the pairing a scan actually reads.
    """

    def __init__(self, model: ReflogModel, parent=None) -> None:
        super().__init__(parent)
        self._model = model

    @staticmethod
    def content_left(rect) -> int:
        """Where a row's content starts, marked or not.

        The orphan stripe's width is reserved on every row. Adding it only to
        the marked rows shifted their text right, undoing the column alignment
        the chip column exists to provide.
        """
        return rect.left() + ROW_PAD + ORPHAN_STRIPE_W

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        meta = QFontMetrics(_meta_font(option.font))
        return QSize(
            option.rect.width(),
            option.fontMetrics.height() + META_GAP + meta.height() + ROW_PAD * 2,
        )

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        entry: ReflogEntry | None = index.data(ENTRY_ROLE)
        if entry is None:
            super().paint(painter, option, index)
            return

        colors = get_theme_manager().current.colors
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        rect = option.rect
        selected = bool(option.state & QStyle.State_Selected)
        if selected:
            painter.fillRect(rect, colors.as_qcolor(ColorRole.PRIMARY))

        fm = option.fontMetrics
        muted = (
            colors.as_qcolor(ColorRole.ON_PRIMARY)
            if selected
            else colors.as_qcolor(ColorRole.ON_SURFACE_VARIANT)
        )
        strong = (
            colors.as_qcolor(ColorRole.ON_PRIMARY)
            if selected
            else colors.as_qcolor(ColorRole.ON_SURFACE)
        )
        meta_fm = QFontMetrics(_meta_font(option.font))
        # Line 1 holds the chip and the summary; line 2 the position, sha and
        # date. Both are laid out from the row's top rather than centred, so a
        # taller row from a scaled font grows downwards and the two stay
        # locked together.
        top = rect.top() + ROW_PAD
        height = fm.height()
        meta_top = top + height + META_GAP
        x = self.content_left(rect)

        # Entries nothing else references are the whole reason the pane exists:
        # the commit list cannot show them at all, and gc takes them when the
        # entry expires. A stripe alone was too quiet to find in a scan, so the
        # row carries a wash of the same colour too.
        if entry.is_orphaned and not selected:
            tint = QColor(colors.as_qcolor(ColorRole.STATUS_DELETED))
            tint.setAlpha(ORPHAN_TINT_ALPHA)
            painter.fillRect(rect, tint)
        if entry.is_orphaned:
            # Full row height, not line 1's: the stripe marks the entry.
            painter.fillRect(
                rect.left(),
                rect.top(),
                ORPHAN_STRIPE_W,
                rect.height(),
                colors.as_qcolor(ColorRole.STATUS_DELETED),
            )

        # Operation chip — coloured so a scan finds resets and rebases fast.
        # The chip is sized to its own label; the column is sized to the widest
        # one, so every summary starts at the same x.
        label = entry.operation or "—"
        chip_w = fm.horizontalAdvance(label) + CHIP_H_PAD * 2
        chip_h = fm.height() + 2
        chip_y = top + (height - chip_h) // 2
        painter.setBrush(_operation_color(entry.operation))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(x, chip_y, chip_w, chip_h, CHIP_RADIUS, CHIP_RADIUS)
        painter.setPen(colors.as_qcolor(ColorRole.ON_BADGE))
        painter.drawText(x, chip_y, chip_w, chip_h, Qt.AlignCenter, label)

        widest = self._model.widest_operation(fm)
        x += max(chip_w, widest + CHIP_H_PAD * 2) + COL_GAP

        right = rect.right() - ROW_PAD
        summary_w = max(right - x, 0)
        painter.setPen(strong)
        painter.drawText(
            x,
            top,
            summary_w,
            height,
            Qt.AlignVCenter,
            fm.elidedText(entry.summary, Qt.ElideRight, summary_w),
        )

        # Where and when, in one run under the summary. Each is short and
        # fixed-width, so they read as a group without needing columns.
        painter.setFont(_meta_font(option.font))
        painter.setPen(muted)
        meta_x = self.content_left(rect)
        meta_h = meta_fm.height()
        for text in (
            f"@{{{entry.index}}}",
            entry.oid_new[:SHA_CHARS],
            f"{entry.timestamp:%Y-%m-%d %H:%M}",
        ):
            painter.drawText(meta_x, meta_top, right - meta_x, meta_h, Qt.AlignVCenter, text)
            meta_x += meta_fm.horizontalAdvance(text) + COL_GAP
        painter.setFont(option.font)

        painter.setPen(colors.as_qcolor(ColorRole.OUTLINE_VARIANT))
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())
        painter.restore()


class _LoadSignals(QObject):
    done = Signal(int, list, object)  # generation, entries, current branch name or None
    failed = Signal(int, str)  # generation, message


class ReflogPane(QWidget):
    """Recent movements of HEAD, shown in the commit list's column."""

    commit_selected = Signal(str)  # oid the ref moved to on the picked row
    restore_requested = Signal(str, str)  # oid to restore to, label for the prompt
    close_requested = Signal()

    def __init__(self, queries: QueryBus, ref: str = "HEAD", parent=None) -> None:
        super().__init__(parent)
        self._queries = queries
        self._ref = ref
        self._branch: str | None = None
        self._last_emitted: str | None = None
        self._load_signals: _LoadSignals | None = None
        # Every window reload reloads this pane too, so loads overlap, and a
        # slow one must not land on top of a newer one.
        self._load_generation = 0

        self._status = ElidingLabel()

        self._show_all_box = QCheckBox("Show every movement")
        self._show_all_box.setToolTip(
            "Include entries where the ref ended up where it started —\n"
            "there is nothing to restore to on those, but they are part of the record."
        )
        self._show_all_box.toggled.connect(self._on_show_all_toggled)

        self._close_btn = QPushButton("✕")
        self._close_btn.setAccessibleName("Close reflog")
        self._close_btn.setFixedSize(28, 28)
        self._close_btn.setToolTip("Close the reflog and show the commit list again (Esc)")
        self._close_btn.clicked.connect(self.close_requested)

        header = QHBoxLayout()
        header.setContentsMargins(8, 6, 8, 6)
        header.addWidget(self._status, 1)
        header.addWidget(self._show_all_box)
        header.addWidget(self._close_btn)

        self._model = ReflogModel()
        self._view = QTableView()
        self._view.setModel(self._model)
        self._view.setItemDelegate(ReflogDelegate(self._model, self._view))
        self._view.setSelectionBehavior(QTableView.SelectRows)
        self._view.setSelectionMode(QTableView.SingleSelection)
        self._view.setShowGrid(False)
        self._view.setEditTriggers(QTableView.NoEditTriggers)
        self._view.verticalHeader().setVisible(False)
        # Follow the delegate rather than the header's fixed 30px default,
        # which silently clipped the row. Measuring every row is bounded here:
        # the pane reads at most `limit` entries.
        self._view.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._view.horizontalHeader().setVisible(False)
        self._view.horizontalHeader().setStretchLastSection(True)
        self._view.setContextMenuPolicy(Qt.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._show_menu)
        self._view.selectionModel().currentRowChanged.connect(self._on_row_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addWidget(self._view, 1)

        connect_widget(self, rebuild=self._view.viewport().update)
        self.reload()

    # ── loading ──────────────────────────────────────────────────────────────

    def reload(self) -> None:
        ref = self._ref
        self._load_generation += 1
        generation = self._load_generation
        self._status.setText(f"Reading the {ref} reflog …")

        signals = _LoadSignals()
        signals.done.connect(self._on_loaded)
        signals.failed.connect(self._on_failed)
        self._load_signals = signals  # prevent GC while the worker runs

        queries = self._queries

        def _worker() -> None:
            try:
                entries = queries.get_reflog.execute(ref)
                # Read in the same load rather than at right-click time: the
                # restore action has to name what it moves, and a blocking repo
                # read while a context menu is opening is the wrong place for it.
                branch = queries.get_repo_state.execute().head_branch
            except Exception as e:  # surfaced in the header, not swallowed
                signals.failed.emit(generation, str(e))
                return
            signals.done.emit(generation, entries, branch)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_loaded(self, generation: int, entries: list[ReflogEntry], branch: str | None) -> None:
        if generation != self._load_generation:
            return
        picked = self.current_entry()
        self._branch = branch
        self._model.reload(entries)
        self._reselect(picked)
        self._update_status()

    def _reselect(self, picked: ReflogEntry | None) -> None:
        """Put the selection back on the movement picked before a reload.

        The model reset clears it, and the pane reloads with every window
        reload. Its commit is still the one in the diff pane, so finding it
        again emits nothing; a pick that is gone is forgotten, so picking
        that commit again hands it over.

        Finding it again must not scroll to it either: the app reloads every
        time it becomes active, and the user may be reading rows far from the
        one they picked.
        """
        row = self._model.row_of(picked) if picked is not None else None
        if row is None:
            self._last_emitted = None
            return
        self._view.setAutoScroll(False)
        try:
            self.select_row(row)
        finally:
            self._view.setAutoScroll(True)

    def _on_show_all_toggled(self, checked: bool) -> None:
        self._model.set_show_all(checked)
        self._update_status()

    def _update_status(self) -> None:
        shown = self._model.rowCount()
        hidden = self._model.hidden_count()
        text = f"{self._ref} — {shown} movements, most recent first"
        if hidden:
            text += f"  ({hidden} that changed nothing hidden)"
        self._status.setText(text)

    def _on_failed(self, generation: int, message: str) -> None:
        if generation != self._load_generation:
            return
        self._branch = None
        self._model.reload([])
        self._status.setText(message)

    # ── interaction ──────────────────────────────────────────────────────────

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.close_requested.emit()
            return
        super().keyPressEvent(event)

    def restore_target(self) -> str:
        """What a restore would actually move.

        The pane reads HEAD's reflog — that is the complete record, since it
        alone spans checkouts between branches. But restoring runs `git reset`,
        which moves the *current branch*, so saying "HEAD" in the action left
        the one thing that changes unnamed. With a detached HEAD there is no
        branch and HEAD itself moves, which is when the old wording was right.
        """
        return self._branch or self._ref

    def current_entry(self) -> ReflogEntry | None:
        return self._model.entry_at(self._view.currentIndex().row())

    def select_row(self, row: int) -> None:
        """Select by index, as a click or a test would."""
        index = self._model.index(row, 0)
        if index.isValid():
            self._view.setCurrentIndex(index)

    def _on_row_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        entry = self._model.entry_at(current.row())
        if entry is None or entry.oid_new == self._last_emitted:
            return
        self._last_emitted = entry.oid_new
        self.commit_selected.emit(entry.oid_new)

    def _show_menu(self, pos) -> None:
        index = self._view.indexAt(pos)
        if not index.isValid():
            return
        self.select_row(index.row())
        entry = self._model.entry_at(index.row())
        if entry is None:
            return

        menu = QMenu(self._view)
        restore = menu.addAction(f"Restore {self.restore_target()} to the state before this")
        # The entry that created the ref has nothing before it to go back to.
        restore.setEnabled(entry.oid_old is not None)
        if entry.oid_old is None:
            restore.setToolTip("This entry created the ref — there is no earlier state")

        if menu.exec(self._view.viewport().mapToGlobal(pos)) is restore and entry.oid_old:
            label = f"@{{{entry.index}}} {entry.operation}: {entry.summary}".strip()
            self.restore_requested.emit(entry.oid_old, label)
