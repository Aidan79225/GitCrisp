from __future__ import annotations
import threading
from datetime import datetime, timedelta, timezone
from PySide6.QtCore import QDate, QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QButtonGroup, QDateEdit, QDialog, QFrame, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)
from git_gui.domain.entities import CommitStat
from git_gui.presentation.bus import QueryBus


# ── Style constants ──────────────────────────────────────────────────────────
ACCENT = "#a371f7"        # purple — matches GitCrisp tag color
GREEN = "#238636"          # additions
RED = "#da3633"            # deletions
CARD_BG = "#161b22"        # card background
BORDER = "#30363d"         # subtle border
MUTED = "#8b949e"          # secondary text


class _LoadSignals(QObject):
    done = Signal(list)  # list[CommitStat]


class InsightDialog(QDialog):
    def __init__(self, queries: QueryBus, parent=None) -> None:
        super().__init__(parent)
        self._queries = queries
        self._stats: list[CommitStat] = []

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
            btn.clicked.connect(lambda _checked=False, l=label: self._on_range_changed(l))
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
        self._loading_label.setStyleSheet(f"color: {MUTED}; padding: 40px;")
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
        now = datetime.now(tz=timezone.utc)
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
            since = datetime(qs.year(), qs.month(), qs.day(), tzinfo=timezone.utc)
            until = datetime(qe.year(), qe.month(), qe.day(), 23, 59, 59, tzinfo=timezone.utc)
            return (since, until)
        return (None, None)

    def _reload(self, since: datetime | None, until: datetime | None) -> None:
        self._loading_label.setVisible(True)
        self._scroll.setVisible(False)

        signals = _LoadSignals()
        signals.done.connect(self._on_loaded)
        self._load_signals = signals  # prevent GC

        queries = self._queries

        def _worker():
            stats = queries.get_commit_stats.execute(since, until)
            signals.done.emit(stats)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_loaded(self, stats: list[CommitStat]) -> None:
        self._stats = stats
        self._loading_label.setVisible(False)
        self._scroll.setVisible(True)
        self._render_content()

    def _render_content(self) -> None:
        # Clear existing content
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        # Placeholder until rendering is implemented in Task 5
        placeholder = QLabel(f"Loaded {len(self._stats)} commits")
        placeholder.setStyleSheet(f"color: {MUTED};")
        self._content_layout.addWidget(placeholder)
        self._content_layout.addStretch()
