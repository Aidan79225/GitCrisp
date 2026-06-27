from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta

from PySide6.QtCore import QDate, QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDateEdit,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from git_gui.presentation.bus import QueryBus
from git_gui.presentation.theme import connect_widget, get_theme_manager

logger = logging.getLogger(__name__)


# ── Style constants ──────────────────────────────────────────────────────────
def _accent() -> str:
    return get_theme_manager().current.colors.ref_badge_tag_bg


def _card_bg() -> str:
    return get_theme_manager().current.colors.surface_container_high


def _border() -> str:
    return get_theme_manager().current.colors.outline


def _muted() -> str:
    return get_theme_manager().current.colors.on_surface_variant


def _green() -> str:
    return get_theme_manager().current.colors.status_added


def _red() -> str:
    return get_theme_manager().current.colors.status_deleted


def _scale_factor() -> float:
    """Effective typography scale for explicitly-sized text.

    The point sizes below are calibrated against the theme's design body
    size. The typography-scale slider (and any platform font adjustment)
    only flows into widgets through the app's default font — painted text
    and fonts built with an absolute ``setPointSize`` would otherwise stay
    fixed. Rescaling by the ratio of the live app font to the design base
    keeps Insight's text tracking the same scale as inherited widget text,
    matching how ``repo_list`` derives its painted fonts.
    """
    app = QApplication.instance()
    design_base = get_theme_manager().current.typography.body_medium.size
    if app is None or design_base <= 0:
        return 1.0
    actual = app.font().pointSizeF()
    if actual <= 0:
        return 1.0
    return actual / design_base


def _scaled_font(point_size: float, *, bold: bool = False) -> QFont:
    """A font at ``point_size`` (design units) scaled to the active typography scale."""
    f = QFont()
    f.setPointSizeF(max(1.0, point_size * _scale_factor()))
    f.setBold(bold)
    return f


class _LoadSignals(QObject):
    progress = Signal(int, float)  # commits_processed, elapsed_seconds
    done = Signal(int, dict, dict, dict, dict, set, int)
    # generation, author_commits, author_added, author_deleted,
    # file_counts, files_changed, total_commits
    cancelled = Signal(int)  # generation
    failed = Signal(int, str)  # generation, message


class _SummaryCard(QFrame):
    def __init__(self, value: str, label: str, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            f"background-color: {_card_bg()}; border: 1px solid {_border()}; border-radius: 8px;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(4)

        value_label = QLabel(value)
        value_label.setFont(_scaled_font(28, bold=True))
        value_label.setStyleSheet(f"color: {_accent()}; border: none;")
        value_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(value_label)

        text_label = QLabel(label)
        text_label.setStyleSheet(f"color: {_muted()}; border: none;")
        text_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(text_label)


class _AuthorRow(QWidget):
    def __init__(
        self,
        rank: int,
        name: str,
        commits: int,
        added: int,
        deleted: int,
        max_total: int,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._rank = rank
        self._name = name
        self._commits = commits
        self._added = added
        self._deleted = deleted
        self._max_total = max_total
        self.setMinimumHeight(64)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()

        # Rank number (large, accent)
        painter.setFont(_scaled_font(20, bold=True))
        painter.setPen(QColor(_accent()))
        painter.drawText(8, 0, 50, rect.height(), Qt.AlignVCenter | Qt.AlignLeft, f"#{self._rank}")

        # Name
        painter.setFont(_scaled_font(11, bold=True))
        name_fm = painter.fontMetrics()
        painter.setPen(get_theme_manager().current.colors.as_qcolor("on_surface"))
        # Strip email from "Name <email>"
        display_name = self._name.split("<")[0].strip() if "<" in self._name else self._name
        painter.drawText(
            64,
            6,
            rect.width() - 200,
            name_fm.height(),
            Qt.AlignVCenter | Qt.AlignLeft,
            display_name,
        )

        # Commit count (right side)
        painter.setFont(_scaled_font(10))
        count_fm = painter.fontMetrics()
        painter.setPen(QColor(_muted()))
        painter.drawText(
            rect.width() - 130,
            6,
            120,
            count_fm.height(),
            Qt.AlignVCenter | Qt.AlignRight,
            f"{self._commits} commits",
        )

        # Bar: green for added, red for deleted (anchored at bottom)
        bar_h = 6
        bar_x = 64
        bar_w = rect.width() - 80
        bar_y = rect.height() - bar_h - 6  # 6px bottom margin

        # Counts above bar
        painter.setFont(_scaled_font(9))
        count_fm = painter.fontMetrics()
        count_h = count_fm.height()
        count_y = bar_y - count_h - 2  # 2px gap above bar
        painter.setPen(QColor(_green()))
        painter.drawText(
            bar_x, count_y, 100, count_h, Qt.AlignVCenter | Qt.AlignLeft, f"+{self._added}"
        )
        painter.setPen(QColor(_red()))
        painter.drawText(
            bar_x, count_y, bar_w, count_h, Qt.AlignVCenter | Qt.AlignRight, f"-{self._deleted}"
        )

        total = self._added + self._deleted
        if total > 0 and self._max_total > 0:
            scale = bar_w / self._max_total
            added_w = int(self._added * scale)
            deleted_w = int(self._deleted * scale)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(_green()))
            painter.drawRoundedRect(bar_x, bar_y, added_w, bar_h, 3, 3)
            painter.setBrush(QColor(_red()))
            painter.drawRoundedRect(bar_x + added_w, bar_y, deleted_w, bar_h, 3, 3)
        painter.end()


class _FileRow(QWidget):
    def __init__(self, rank: int, path: str, count: int, max_count: int, parent=None) -> None:
        super().__init__(parent)
        self._rank = rank
        self._path = path
        self._count = count
        self._max_count = max_count
        self.setMinimumHeight(40)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()

        painter.setFont(_scaled_font(16, bold=True))
        painter.setPen(QColor(_accent()))
        painter.drawText(8, 0, 50, rect.height(), Qt.AlignVCenter | Qt.AlignLeft, f"#{self._rank}")

        painter.setFont(_scaled_font(10))
        path_fm = painter.fontMetrics()
        painter.setPen(get_theme_manager().current.colors.as_qcolor("on_surface"))
        # Elide long paths
        elided = path_fm.elidedText(self._path, Qt.ElideMiddle, rect.width() - 200)
        painter.drawText(
            56, 0, rect.width() - 200, rect.height(), Qt.AlignVCenter | Qt.AlignLeft, elided
        )

        painter.setFont(_scaled_font(10))
        painter.setPen(QColor(_muted()))
        painter.drawText(
            rect.width() - 140,
            0,
            130,
            rect.height(),
            Qt.AlignVCenter | Qt.AlignRight,
            f"{self._count}×",
        )
        painter.end()


def _make_card_container(title: str) -> tuple[QFrame, QVBoxLayout]:
    """Create a styled card with a title; returns (frame, inner_layout)."""
    frame = QFrame()
    frame.setStyleSheet(
        f"background-color: {_card_bg()}; border: 1px solid {_border()}; border-radius: 8px;"
    )
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(8)

    title_label = QLabel(title)
    title_label.setFont(_scaled_font(13, bold=True))
    title_label.setStyleSheet(
        f"color: {get_theme_manager().current.colors.on_surface}; border: none;"
    )
    layout.addWidget(title_label)

    return frame, layout


class InsightDialog(QDialog):
    def __init__(self, queries: QueryBus, parent=None) -> None:
        super().__init__(parent)
        self._queries = queries
        self._load_generation = 0
        self._cancel: threading.Event | None = None
        self._last_render: tuple | None = None

        self.setWindowTitle("Git Insight")
        self.resize(700, 800)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Time range buttons
        self._range_bar = QHBoxLayout()
        self._range_group = QButtonGroup(self)
        self._range_group.setExclusive(True)
        for label in ("This Week", "This Month", "This Year", "All", "Custom"):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _checked=False, lbl=label: self._on_range_changed(lbl))
            self._range_group.addButton(btn)
            self._range_bar.addWidget(btn)
        self._range_bar.addStretch()
        layout.addLayout(self._range_bar)

        # Custom date pickers (hidden unless Custom selected)
        self._custom_bar = QHBoxLayout()
        self._start_date = QDateEdit()
        self._start_date.setCalendarPopup(True)
        self._start_date.setDate(QDate.currentDate().addMonths(-1))
        self._end_date = QDateEdit()
        self._end_date.setCalendarPopup(True)
        self._end_date.setDate(QDate.currentDate())
        self._start_date.dateChanged.connect(lambda _d: self._reload_if_custom())
        self._end_date.dateChanged.connect(lambda _d: self._reload_if_custom())
        self._custom_bar.addWidget(QLabel("From:"))
        self._custom_bar.addWidget(self._start_date)
        self._custom_bar.addWidget(QLabel("To:"))
        self._custom_bar.addWidget(self._end_date)
        self._custom_bar.addStretch()
        self._custom_widget = QWidget()
        self._custom_widget.setLayout(self._custom_bar)
        self._custom_widget.setVisible(False)
        layout.addWidget(self._custom_widget)

        # Loading label
        self._loading_label = QLabel("Loading...")
        self._loading_label.setAlignment(Qt.AlignCenter)
        self._loading_label.setStyleSheet(f"color: {_muted()}; padding: 40px;")
        layout.addWidget(self._loading_label)

        # Scroll area for content
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(16)
        self._scroll.setWidget(self._content)
        self._scroll.setVisible(False)
        layout.addWidget(self._scroll, 1)

        # Default selection: This Month
        for btn in self._range_group.buttons():
            if btn.text() == "This Month":
                btn.setChecked(True)
                break
        self._on_range_changed("This Month")

        self._rebuild_styles()
        connect_widget(self, rebuild=self._rebuild_styles)

    def _rebuild_styles(self) -> None:
        self._loading_label.setStyleSheet(f"color: {_muted()}; padding: 40px;")
        if self._last_render is not None:
            self._render_content(*self._last_render)
        self.update()

    def closeEvent(self, event) -> None:
        if self._cancel is not None:
            self._cancel.set()
        super().closeEvent(event)

    def _on_range_changed(self, label: str) -> None:
        self._custom_widget.setVisible(label == "Custom")
        since, until = self._compute_range(label)
        self._reload(since, until)

    def _reload_if_custom(self) -> None:
        # Only re-query if Custom is currently selected
        for btn in self._range_group.buttons():
            if btn.isChecked() and btn.text() == "Custom":
                since, until = self._compute_range("Custom")
                self._reload(since, until)
                return

    def _compute_range(self, label: str) -> tuple[datetime | None, datetime | None]:
        now = datetime.now(tz=UTC)
        if label == "This Week":
            start = now - timedelta(days=now.weekday())
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            return (start, None)
        if label == "This Month":
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            return (start, None)
        if label == "This Year":
            start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            return (start, None)
        if label == "All":
            return (None, None)
        if label == "Custom":
            qs = self._start_date.date()
            qe = self._end_date.date()
            since = datetime(qs.year(), qs.month(), qs.day(), tzinfo=UTC)
            until = datetime(qe.year(), qe.month(), qe.day(), 23, 59, 59, tzinfo=UTC)
            return (since, until)
        return (None, None)

    def _reload(self, since: datetime | None, until: datetime | None) -> None:
        # Cancel any in-flight worker — we're superseding it.
        if self._cancel is not None:
            self._cancel.set()

        self._loading_label.setText("Loading...")
        self._loading_label.setVisible(True)
        self._scroll.setVisible(False)

        self._load_generation += 1
        generation = self._load_generation
        self._cancel = threading.Event()
        cancel_event = self._cancel

        signals = _LoadSignals()
        signals.progress.connect(self._on_progress)
        signals.done.connect(self._on_loaded)
        signals.cancelled.connect(self._on_cancelled)
        signals.failed.connect(self._on_failed)
        self._load_signals = signals  # prevent GC

        queries = self._queries

        def _worker() -> None:
            import time

            author_commits: dict[str, int] = {}
            author_added: dict[str, int] = {}
            author_deleted: dict[str, int] = {}
            file_counts: dict[str, int] = {}
            files_changed: set[str] = set()
            total = 0
            started = time.monotonic()
            last_progress = started

            try:
                for cs in queries.get_commit_stats.execute(
                    since, until, cancel=cancel_event.is_set
                ):
                    total += 1
                    author_commits[cs.author] = author_commits.get(cs.author, 0) + 1
                    for f in cs.files:
                        author_added[cs.author] = author_added.get(cs.author, 0) + f.added
                        author_deleted[cs.author] = author_deleted.get(cs.author, 0) + f.deleted
                        file_counts[f.path] = file_counts.get(f.path, 0) + 1
                        files_changed.add(f.path)

                    now = time.monotonic()
                    if now - last_progress >= 0.25:
                        signals.progress.emit(total, now - started)
                        last_progress = now
            except Exception as e:
                # Don't silently produce an empty-looking result — the user
                # needs to know whether Insight saw nothing or whether it
                # crashed mid-walk.
                logger.exception("Insight worker failed")
                if not cancel_event.is_set():
                    signals.failed.emit(generation, f"{type(e).__name__}: {e}")
                    return

            if cancel_event.is_set():
                signals.cancelled.emit(generation)
                return

            signals.done.emit(
                generation,
                author_commits,
                author_added,
                author_deleted,
                file_counts,
                files_changed,
                total,
            )

        threading.Thread(target=_worker, daemon=True).start()

    def _on_loaded(
        self,
        generation: int,
        author_commits: dict,
        author_added: dict,
        author_deleted: dict,
        file_counts: dict,
        files_changed: set,
        total_commits: int,
    ) -> None:
        if generation != self._load_generation:
            return
        self._loading_label.setVisible(False)
        self._scroll.setVisible(True)
        self._render_content(
            author_commits,
            author_added,
            author_deleted,
            file_counts,
            files_changed,
            total_commits,
        )

    def _on_cancelled(self, generation: int) -> None:
        # Worker was cancelled (closeEvent or supersession). Nothing to render.
        if generation != self._load_generation:
            return
        # Keep the loading label visible briefly so a fast cancel still
        # shows that we acknowledged it; closeEvent will tear the dialog
        # down anyway.
        self._loading_label.setText("Cancelled.")

    def _on_failed(self, generation: int, message: str) -> None:
        if generation != self._load_generation:
            return
        self._loading_label.setText(f"Insight failed: {message}")
        self._loading_label.setVisible(True)
        self._scroll.setVisible(False)

    def _on_progress(self, total: int, elapsed: float) -> None:
        # Format with thousands separator for readability on huge repos.
        self._loading_label.setText(f"Processed {total:,} commits, {elapsed:.1f}s...")

    def _render_content(
        self,
        author_commits: dict[str, int],
        author_added: dict[str, int],
        author_deleted: dict[str, int],
        file_counts: dict[str, int],
        files_changed: set[str],
        total_commits: int,
    ) -> None:
        self._last_render = (
            author_commits,
            author_added,
            author_deleted,
            file_counts,
            files_changed,
            total_commits,
        )

        # Clear existing content
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if total_commits == 0:
            empty = QLabel("No commits in this time range")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(f"color: {_muted()}; padding: 40px;")
            self._content_layout.addWidget(empty)
            self._content_layout.addStretch()
            return

        active_authors = len(author_commits)
        total_files = len(files_changed)

        # ── Summary cards row ────────────────────────────────────────────────
        summary_row = QHBoxLayout()
        summary_row.setSpacing(12)
        summary_row.addWidget(_SummaryCard(str(total_commits), "Total Commits"))
        summary_row.addWidget(_SummaryCard(str(active_authors), "Active Authors"))
        summary_row.addWidget(_SummaryCard(str(total_files), "Files Changed"))
        summary_widget = QWidget()
        summary_widget.setLayout(summary_row)
        self._content_layout.addWidget(summary_widget)

        # ── Top Authors card ─────────────────────────────────────────────────
        top_authors = sorted(author_commits.items(), key=lambda x: x[1], reverse=True)[:10]
        max_total = max(
            (author_added.get(a, 0) + author_deleted.get(a, 0) for a, _ in top_authors),
            default=0,
        )
        authors_frame, authors_layout = _make_card_container("Top Authors")
        for i, (author, count) in enumerate(top_authors, start=1):
            row = _AuthorRow(
                rank=i,
                name=author,
                commits=count,
                added=author_added.get(author, 0),
                deleted=author_deleted.get(author, 0),
                max_total=max_total,
            )
            authors_layout.addWidget(row)
        self._content_layout.addWidget(authors_frame)

        # ── Most Modified Files card ─────────────────────────────────────────
        top_files = sorted(file_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        max_count = top_files[0][1] if top_files else 0
        files_frame, files_layout = _make_card_container("Most Modified Files")
        for i, (path, count) in enumerate(top_files, start=1):
            row = _FileRow(rank=i, path=path, count=count, max_count=max_count)
            files_layout.addWidget(row)
        self._content_layout.addWidget(files_frame)

        self._content_layout.addStretch()
