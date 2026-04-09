# Git Insight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Spotify Wrapped-style insight dialog showing author commit stats, lines added/deleted, and most modified files with time range filtering.

**Architecture:** Single `git log --numstat` query in infrastructure produces `CommitStat` entities. Application layer exposes `GetCommitStats(since, until)` query. A new `InsightDialog` opened from a graph toolbar button performs aggregation in the dialog and displays results in custom-painted Wrapped-style cards.

**Tech Stack:** Python 3.13, PySide6, subprocess (git CLI)

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `git_gui/domain/entities.py` | Modify | Add `FileStat`, `CommitStat` dataclasses |
| `git_gui/domain/ports.py` | Modify | Add `get_commit_stats` to `IRepositoryReader` |
| `git_gui/infrastructure/pygit2_repo.py` | Modify | Implement `get_commit_stats` via `git log --numstat` |
| `git_gui/application/queries.py` | Modify | Add `GetCommitStats` query |
| `git_gui/presentation/bus.py` | Modify | Add `get_commit_stats` to `QueryBus` |
| `git_gui/presentation/widgets/insight_dialog.py` | Create | Wrapped-style dialog with aggregation + display |
| `git_gui/presentation/widgets/graph.py` | Modify | Add insight toolbar button + signal |
| `git_gui/presentation/main_window.py` | Modify | Wire button to open dialog |
| `tests/domain/test_entities.py` | Modify | Test new dataclasses |
| `tests/infrastructure/test_reads.py` | Modify | Test get_commit_stats |

---

### Task 1: Domain entities and ports

**Files:**
- Modify: `git_gui/domain/entities.py`
- Modify: `git_gui/domain/ports.py`
- Test: `tests/domain/test_entities.py`

- [ ] **Step 1: Write failing test**

Add to `tests/domain/test_entities.py`:

```python
from git_gui.domain.entities import CommitStat, FileStat
from datetime import datetime, timezone


def test_file_stat():
    fs = FileStat(path="src/main.py", added=10, deleted=2)
    assert fs.path == "src/main.py"
    assert fs.added == 10
    assert fs.deleted == 2


def test_commit_stat():
    ts = datetime(2026, 4, 1, tzinfo=timezone.utc)
    cs = CommitStat(
        oid="abc123",
        author="Alice <alice@example.com>",
        timestamp=ts,
        files=[FileStat(path="a.py", added=5, deleted=1)],
    )
    assert cs.oid == "abc123"
    assert cs.author == "Alice <alice@example.com>"
    assert len(cs.files) == 1
    assert cs.files[0].added == 5
```

- [ ] **Step 2: Run test, verify it fails**

Run: `uv run pytest tests/domain/test_entities.py::test_file_stat -v`
Expected: FAIL — `ImportError: cannot import name 'CommitStat'`

- [ ] **Step 3: Add entities**

Add to `git_gui/domain/entities.py` after the `Tag` dataclass:

```python
@dataclass
class FileStat:
    path: str
    added: int
    deleted: int


@dataclass
class CommitStat:
    oid: str
    author: str
    timestamp: datetime
    files: list[FileStat]
```

- [ ] **Step 4: Add port method**

In `git_gui/domain/ports.py`, update the import:

```python
from git_gui.domain.entities import Branch, Commit, CommitStat, FileStatus, Hunk, Stash, Tag
```

Add to `IRepositoryReader` after `get_remote_tags`:

```python
    def get_commit_stats(self, since: datetime | None = None, until: datetime | None = None) -> list[CommitStat]: ...
```

You'll need to add the datetime import at the top:

```python
from datetime import datetime
```

- [ ] **Step 5: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add git_gui/domain/entities.py git_gui/domain/ports.py tests/domain/test_entities.py
git commit -m "feat: add CommitStat and FileStat entities"
```

---

### Task 2: Infrastructure get_commit_stats

**Files:**
- Modify: `git_gui/infrastructure/pygit2_repo.py`
- Test: `tests/infrastructure/test_reads.py`

- [ ] **Step 1: Write failing test**

Add to `tests/infrastructure/test_reads.py`:

```python
def test_get_commit_stats_returns_initial_commit(repo_impl):
    stats = repo_impl.get_commit_stats()
    assert len(stats) == 1
    assert stats[0].author == "Test User <test@example.com>" or "Test User" in stats[0].author
    assert len(stats[0].files) == 1
    assert stats[0].files[0].path == "README.md"
    assert stats[0].files[0].added >= 1


def test_get_commit_stats_with_multiple_commits(repo_path, repo_impl):
    raw = pygit2.Repository(str(repo_path))
    sig = pygit2.Signature("Author Two", "two@example.com")
    (repo_path / "second.txt").write_text("line1\nline2\nline3\n")
    raw.index.add("second.txt")
    raw.index.write()
    tree = raw.index.write_tree()
    head_oid = raw.head.target
    raw.create_commit("refs/heads/master", sig, sig, "Add second", tree, [head_oid])

    stats = repo_impl.get_commit_stats()
    assert len(stats) == 2
    authors = [s.author for s in stats]
    assert any("Author Two" in a for a in authors)
    assert any("Test User" in a for a in authors)
```

- [ ] **Step 2: Run test, verify it fails**

Run: `uv run pytest tests/infrastructure/test_reads.py::test_get_commit_stats_returns_initial_commit -v`
Expected: FAIL — `AttributeError: 'Pygit2Repository' object has no attribute 'get_commit_stats'`

- [ ] **Step 3: Implement get_commit_stats**

In `git_gui/infrastructure/pygit2_repo.py`, update the entities import to include the new types:

```python
from git_gui.domain.entities import (
    Branch, Commit, CommitStat, FileStat, FileStatus, Hunk, Stash, Tag, WORKING_TREE_OID,
)
```

Add to `Pygit2Repository` in the reads section, after `get_remote_tags`:

```python
    def get_commit_stats(self, since: datetime | None = None, until: datetime | None = None) -> list[CommitStat]:
        cmd = ["git", "log", "--numstat", "--format=__COMMIT__%n%H%n%aN <%aE>%n%aI"]
        if since:
            cmd.append(f"--since={since.isoformat()}")
        if until:
            cmd.append(f"--until={until.isoformat()}")
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                cwd=self._repo.workdir, **subprocess_kwargs(),
            )
            if result.returncode != 0:
                return []
        except Exception:
            return []

        stats: list[CommitStat] = []
        current_oid: str | None = None
        current_author: str | None = None
        current_ts: datetime | None = None
        current_files: list[FileStat] = []
        state = "expect_marker"  # expect_marker | oid | author | date | files

        def flush() -> None:
            if current_oid and current_author and current_ts is not None:
                stats.append(CommitStat(
                    oid=current_oid,
                    author=current_author,
                    timestamp=current_ts,
                    files=list(current_files),
                ))

        for raw_line in result.stdout.splitlines():
            line = raw_line.rstrip("\r")
            if line == "__COMMIT__":
                flush()
                current_oid = None
                current_author = None
                current_ts = None
                current_files = []
                state = "oid"
                continue
            if state == "oid":
                current_oid = line
                state = "author"
                continue
            if state == "author":
                current_author = line
                state = "date"
                continue
            if state == "date":
                try:
                    current_ts = datetime.fromisoformat(line)
                except ValueError:
                    current_ts = None
                state = "files"
                continue
            if state == "files":
                if not line.strip():
                    continue
                # numstat format: "<added>\t<deleted>\t<path>"
                parts = line.split("\t")
                if len(parts) != 3:
                    continue
                added_str, deleted_str, path = parts
                try:
                    added = int(added_str) if added_str != "-" else 0
                    deleted = int(deleted_str) if deleted_str != "-" else 0
                except ValueError:
                    continue
                current_files.append(FileStat(path=path, added=added, deleted=deleted))

        flush()
        return stats
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest tests/infrastructure/test_reads.py -v`
Expected: PASS

- [ ] **Step 5: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add git_gui/infrastructure/pygit2_repo.py tests/infrastructure/test_reads.py
git commit -m "feat: implement get_commit_stats via git log --numstat"
```

---

### Task 3: Application query and bus

**Files:**
- Modify: `git_gui/application/queries.py`
- Modify: `git_gui/presentation/bus.py`

- [ ] **Step 1: Add GetCommitStats query**

In `git_gui/application/queries.py`, update the entities import:

```python
from git_gui.domain.entities import Branch, Commit, CommitStat, FileStatus, Hunk, Stash, Tag
```

Add datetime import at top if not already present:

```python
from datetime import datetime
```

Add the query class after `GetRemoteTags`:

```python
class GetCommitStats:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self, since: datetime | None = None, until: datetime | None = None) -> list[CommitStat]:
        return self._reader.get_commit_stats(since, until)
```

- [ ] **Step 2: Wire into bus**

In `git_gui/presentation/bus.py`, add `GetCommitStats` to the queries import:

```python
from git_gui.application.queries import (
    GetCommitGraph, GetBranches, GetStashes, GetTags, GetRemoteTags, GetCommitStats,
    GetCommitFiles, GetFileDiff, GetStagedDiff, GetWorkingTree,
    GetCommitDetail, IsDirty, GetHeadOid,
)
```

Add field to `QueryBus` (after `get_remote_tags`):

```python
    get_commit_stats: GetCommitStats
```

Add to `from_reader`:

```python
            get_commit_stats=GetCommitStats(reader),
```

- [ ] **Step 3: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add git_gui/application/queries.py git_gui/presentation/bus.py
git commit -m "feat: add GetCommitStats query and wire into bus"
```

---

### Task 4: InsightDialog — structure and time range

**Files:**
- Create: `git_gui/presentation/widgets/insight_dialog.py`

- [ ] **Step 1: Create InsightDialog skeleton**

Create `git_gui/presentation/widgets/insight_dialog.py`:

```python
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
        # Placeholder until rendering is implemented in next task
        placeholder = QLabel(f"Loaded {len(self._stats)} commits")
        placeholder.setStyleSheet(f"color: {MUTED};")
        self._content_layout.addWidget(placeholder)
        self._content_layout.addStretch()
```

- [ ] **Step 2: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS (no new tests yet, just verifying nothing broke)

- [ ] **Step 3: Commit**

```bash
git add git_gui/presentation/widgets/insight_dialog.py
git commit -m "feat: add InsightDialog skeleton with time range selector"
```

---

### Task 5: InsightDialog — Wrapped-style cards

**Files:**
- Modify: `git_gui/presentation/widgets/insight_dialog.py`

- [ ] **Step 1: Add aggregation helpers and cards**

In `git_gui/presentation/widgets/insight_dialog.py`, replace the `_render_content` method and add helper methods + classes.

First, add this `_StatCard` class above `InsightDialog`:

```python
class _SummaryCard(QFrame):
    def __init__(self, value: str, label: str, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            f"background-color: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 8px;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(4)

        value_label = QLabel(value)
        value_font = QFont()
        value_font.setPointSize(28)
        value_font.setBold(True)
        value_label.setFont(value_font)
        value_label.setStyleSheet(f"color: {ACCENT}; border: none;")
        value_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(value_label)

        text_label = QLabel(label)
        text_label.setStyleSheet(f"color: {MUTED}; border: none;")
        text_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(text_label)


class _AuthorRow(QWidget):
    def __init__(self, rank: int, name: str, commits: int,
                 added: int, deleted: int, max_total: int, parent=None) -> None:
        super().__init__(parent)
        self._rank = rank
        self._name = name
        self._commits = commits
        self._added = added
        self._deleted = deleted
        self._max_total = max_total
        self.setMinimumHeight(56)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        fm = painter.fontMetrics()

        # Rank number (large, accent)
        rank_font = QFont()
        rank_font.setPointSize(20)
        rank_font.setBold(True)
        painter.setFont(rank_font)
        painter.setPen(QColor(ACCENT))
        painter.drawText(8, 0, 50, rect.height(), Qt.AlignVCenter | Qt.AlignLeft, f"#{self._rank}")

        # Name
        name_font = QFont()
        name_font.setPointSize(11)
        name_font.setBold(True)
        painter.setFont(name_font)
        painter.setPen(QColor("white"))
        # Strip email from "Name <email>"
        display_name = self._name.split("<")[0].strip() if "<" in self._name else self._name
        painter.drawText(64, 6, rect.width() - 200, fm.height(),
                         Qt.AlignVCenter | Qt.AlignLeft, display_name)

        # Commit count (right side)
        count_font = QFont()
        count_font.setPointSize(10)
        painter.setFont(count_font)
        painter.setPen(QColor(MUTED))
        painter.drawText(rect.width() - 130, 6, 120, fm.height(),
                         Qt.AlignVCenter | Qt.AlignRight, f"{self._commits} commits")

        # Bar: green for added, red for deleted
        bar_y = rect.height() - 18
        bar_x = 64
        bar_w = rect.width() - 80
        bar_h = 6
        total = self._added + self._deleted
        if total > 0 and self._max_total > 0:
            scale = bar_w / self._max_total
            added_w = int(self._added * scale)
            deleted_w = int(self._deleted * scale)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(GREEN))
            painter.drawRoundedRect(bar_x, bar_y, added_w, bar_h, 3, 3)
            painter.setBrush(QColor(RED))
            painter.drawRoundedRect(bar_x + added_w, bar_y, deleted_w, bar_h, 3, 3)

        # Counts under bar
        count_font2 = QFont()
        count_font2.setPointSize(9)
        painter.setFont(count_font2)
        painter.setPen(QColor(GREEN))
        painter.drawText(bar_x, bar_y - 2, 100, 12, Qt.AlignTop | Qt.AlignLeft,
                         f"+{self._added}")
        painter.setPen(QColor(RED))
        painter.drawText(bar_x, bar_y - 2, bar_w, 12, Qt.AlignTop | Qt.AlignRight,
                         f"-{self._deleted}")
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
        fm = painter.fontMetrics()

        rank_font = QFont()
        rank_font.setPointSize(16)
        rank_font.setBold(True)
        painter.setFont(rank_font)
        painter.setPen(QColor(ACCENT))
        painter.drawText(8, 0, 50, rect.height(), Qt.AlignVCenter | Qt.AlignLeft, f"#{self._rank}")

        path_font = QFont()
        path_font.setPointSize(10)
        painter.setFont(path_font)
        painter.setPen(QColor("white"))
        # Elide long paths
        elided = fm.elidedText(self._path, Qt.ElideMiddle, rect.width() - 200)
        painter.drawText(56, 0, rect.width() - 200, rect.height(),
                         Qt.AlignVCenter | Qt.AlignLeft, elided)

        count_font = QFont()
        count_font.setPointSize(10)
        painter.setFont(count_font)
        painter.setPen(QColor(MUTED))
        painter.drawText(rect.width() - 140, 0, 130, rect.height(),
                         Qt.AlignVCenter | Qt.AlignRight, f"{self._count}×")
        painter.end()


def _make_card_container(title: str) -> tuple[QFrame, QVBoxLayout]:
    """Create a styled card with a title; returns (frame, inner_layout)."""
    frame = QFrame()
    frame.setStyleSheet(
        f"background-color: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 8px;"
    )
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(8)

    title_label = QLabel(title)
    title_font = QFont()
    title_font.setPointSize(13)
    title_font.setBold(True)
    title_label.setFont(title_font)
    title_label.setStyleSheet("color: white; border: none;")
    layout.addWidget(title_label)

    return frame, layout
```

Replace the `_render_content` method with:

```python
    def _render_content(self) -> None:
        # Clear existing content
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not self._stats:
            empty = QLabel("No commits in this time range")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(f"color: {MUTED}; padding: 40px;")
            self._content_layout.addWidget(empty)
            self._content_layout.addStretch()
            return

        # ── Aggregation ──────────────────────────────────────────────────────
        author_commits: dict[str, int] = {}
        author_added: dict[str, int] = {}
        author_deleted: dict[str, int] = {}
        file_counts: dict[str, int] = {}
        files_changed: set[str] = set()

        for cs in self._stats:
            author_commits[cs.author] = author_commits.get(cs.author, 0) + 1
            for f in cs.files:
                author_added[cs.author] = author_added.get(cs.author, 0) + f.added
                author_deleted[cs.author] = author_deleted.get(cs.author, 0) + f.deleted
                file_counts[f.path] = file_counts.get(f.path, 0) + 1
                files_changed.add(f.path)

        total_commits = len(self._stats)
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
                rank=i, name=author, commits=count,
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
```

- [ ] **Step 2: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add git_gui/presentation/widgets/insight_dialog.py
git commit -m "feat: implement Wrapped-style cards in InsightDialog"
```

---

### Task 6: Toolbar button + MainWindow wiring

**Files:**
- Modify: `git_gui/presentation/widgets/graph.py`
- Modify: `git_gui/presentation/main_window.py`

- [ ] **Step 1: Add insight signal and toolbar button to GraphWidget**

In `git_gui/presentation/widgets/graph.py`, add to the signal declarations (after `stash_requested`):

```python
    insight_requested = Signal()
```

In the `__init__` method, find the toolbar button loop (around line 131-143) and update it to include the insight button:

```python
        for icon_name, tooltip, signal in [
            ("ic_reload", "Reload (F5)", self.reload_requested),
            ("ic_push", "Push", self.push_requested),
            ("ic_pull", "Pull", self.pull_requested),
            ("ic_fetch", "Fetch All --prune", self.fetch_all_requested),
            ("ic_insight", "Git Insight", self.insight_requested),
        ]:
            btn = QPushButton()
            btn.setIcon(QIcon(str(_ARTS / f"{icon_name}.svg")))
            btn.setIconSize(QSize(28, 28))
            btn.setToolTip(tooltip)
            btn.setStyleSheet(_BTN_STYLE)
            btn.clicked.connect(signal.emit)
            header_bar.addWidget(btn)
```

- [ ] **Step 2: Wire signal in MainWindow**

In `git_gui/presentation/main_window.py`, add the import:

```python
from git_gui.presentation.widgets.insight_dialog import InsightDialog
```

Add the signal connection in `__init__`, after `self._graph.create_tag_requested.connect(self._on_create_tag)`:

```python
        self._graph.insight_requested.connect(self._on_insight_requested)
```

Add the handler method (place it near other graph signal handlers):

```python
    def _on_insight_requested(self) -> None:
        if self._queries is None:
            return
        dialog = InsightDialog(self._queries, self)
        dialog.exec()
```

- [ ] **Step 3: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add git_gui/presentation/widgets/graph.py git_gui/presentation/main_window.py
git commit -m "feat: add Git Insight toolbar button and wire dialog"
```

---

### Task 7: End-to-end verification

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: Manual verification**

Run: `uv run python main.py`

Verify:
1. Open a repo with multiple commits and authors
2. Click the new insight icon button in the graph toolbar — InsightDialog opens
3. Default range is "This Month" — shows summary cards, top authors, top files
4. Click "This Week" — content updates with current week's data
5. Click "This Year" — content updates with year's data
6. Click "All" — content updates with full history
7. Click "Custom" — date pickers appear; changing dates triggers re-query
8. Summary cards show correct numbers (commits, authors, files)
9. Top Authors card shows ranked list with green/red bars for added/deleted
10. Most Modified Files card shows ranked list with file paths
11. Time range with no commits shows "No commits in this time range"
12. Close dialog — main window returns to normal state
