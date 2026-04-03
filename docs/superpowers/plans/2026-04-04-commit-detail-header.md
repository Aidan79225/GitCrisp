# Commit Detail Header Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two rows above the commit diff area showing commit metadata (author, datetime, hash, parents, refs) and the full commit message.

**Architecture:** Add `get_commit(oid)` to the reader port and wire it through queries/bus. Create a `CommitDetailWidget` that custom-paints 3 lines with badge pills for refs. Add a message `QPlainTextEdit`. Insert both above the existing file list + diff splitter in `DiffWidget`.

**Tech Stack:** Python 3.13, PySide6 6.11, pytest, pytest-qt

---

## File Map

| File | Change |
|------|--------|
| `git_gui/domain/ports.py` | Add `get_commit(oid) -> Commit` to `IRepositoryReader` |
| `git_gui/infrastructure/pygit2_repo.py` | Implement `get_commit(oid)` |
| `git_gui/application/queries.py` | Add `GetCommitDetail` |
| `git_gui/presentation/bus.py` | Wire `get_commit_detail` on `QueryBus` |
| `git_gui/presentation/widgets/commit_detail.py` | New — custom-painted 3-line commit metadata widget |
| `git_gui/presentation/widgets/diff.py` | Add detail + message rows above existing splitter |
| `tests/infrastructure/test_reads.py` | Add test for `get_commit` |

---

## Task 1: Domain + Infrastructure + Query — get_commit

**Files:**
- Modify: `git_gui/domain/ports.py`
- Modify: `git_gui/infrastructure/pygit2_repo.py`
- Modify: `git_gui/application/queries.py`
- Modify: `git_gui/presentation/bus.py`
- Modify: `tests/infrastructure/test_reads.py`

**Context:** Add a new reader port method `get_commit(oid) -> Commit` that retrieves a single commit by OID. Wire it through query and bus layers.

- [ ] **Step 1: Write the failing test**

Add to `tests/infrastructure/test_reads.py`:

```python
def test_get_commit_returns_commit(repo_impl):
    commits = repo_impl.get_commits(limit=1)
    oid = commits[0].oid
    commit = repo_impl.get_commit(oid)
    assert commit.oid == oid
    assert commit.message == "Initial commit"
    assert "Test User" in commit.author
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/infrastructure/test_reads.py::test_get_commit_returns_commit -v
```

Expected: FAIL with `AttributeError: 'Pygit2Repository' object has no attribute 'get_commit'`

- [ ] **Step 3: Add port method**

In `git_gui/domain/ports.py`, add to `IRepositoryReader` after `get_commits`:

```python
    def get_commit(self, oid: str) -> Commit: ...
```

- [ ] **Step 4: Implement in Pygit2Repository**

In `git_gui/infrastructure/pygit2_repo.py`, add after `get_commits`:

```python
    def get_commit(self, oid: str) -> Commit:
        return _commit_to_entity(self._repo.get(oid))
```

- [ ] **Step 5: Run test**

```bash
uv run pytest tests/infrastructure/test_reads.py::test_get_commit_returns_commit -v
```

Expected: PASS

- [ ] **Step 6: Add query class**

At the end of `git_gui/application/queries.py`, add:

```python
class GetCommitDetail:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self, oid: str) -> Commit:
        return self._reader.get_commit(oid)
```

- [ ] **Step 7: Wire to QueryBus**

In `git_gui/presentation/bus.py`, update import:

```python
from git_gui.application.queries import (
    GetCommitGraph, GetBranches, GetStashes,
    GetCommitFiles, GetFileDiff, GetStagedDiff, GetWorkingTree,
    GetCommitDetail,
)
```

Add field to `QueryBus` dataclass:

```python
    get_commit_detail: GetCommitDetail
```

Add to `from_reader`:

```python
            get_commit_detail=GetCommitDetail(reader),
```

- [ ] **Step 8: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 9: Commit**

```bash
git add git_gui/domain/ports.py git_gui/infrastructure/pygit2_repo.py git_gui/application/queries.py git_gui/presentation/bus.py tests/infrastructure/test_reads.py
git commit -m "feat: add get_commit query for single commit lookup"
```

---

## Task 2: CommitDetailWidget — custom-painted 3-line metadata

**Files:**
- Create: `git_gui/presentation/widgets/commit_detail.py`

**Context:** A custom `QWidget` that paints 3 lines of commit metadata. Line 1: author + datetime. Line 2: full hash + branch/tag badges. Line 3: parent hash(es). Uses `_badge_color` from `ref_badge_delegate.py` for colored pills. No tests — presentation-only.

- [ ] **Step 1: Create `git_gui/presentation/widgets/commit_detail.py`**

```python
# git_gui/presentation/widgets/commit_detail.py
from __future__ import annotations
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QBrush, QColor, QPainter
from PySide6.QtWidgets import QWidget
from git_gui.domain.entities import Commit
from git_gui.presentation.widgets.ref_badge_delegate import (
    _badge_color, BADGE_RADIUS, BADGE_H_PAD, BADGE_V_PAD, BADGE_GAP,
)

MUTED = "#8b949e"
PAD = 8


class CommitDetailWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._commit: Commit | None = None
        self._refs: list[str] = []

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

        # ── Line 1: Author + datetime ────────────────────────────────────────
        y = PAD
        painter.setPen(QColor(MUTED))
        painter.drawText(PAD, y + fm.ascent(), "Author: ")
        label_w = fm.horizontalAdvance("Author: ")
        painter.setPen(QColor("white"))
        painter.drawText(PAD + label_w, y + fm.ascent(), c.author)
        ts = c.timestamp.strftime("%Y-%m-%d %H:%M")
        ts_w = fm.horizontalAdvance(ts)
        painter.setPen(QColor(MUTED))
        painter.drawText(w - PAD - ts_w, y + fm.ascent(), ts)

        # ── Line 2: Hash + ref badges ────────────────────────────────────────
        y += line_h + PAD
        painter.setPen(QColor(MUTED))
        painter.drawText(PAD, y + fm.ascent(), "Commit: ")
        x = PAD + fm.horizontalAdvance("Commit: ")
        painter.setPen(QColor("white"))
        painter.drawText(x, y + fm.ascent(), c.oid)
        x += fm.horizontalAdvance(c.oid) + BADGE_GAP * 2

        badge_h = line_h + BADGE_V_PAD * 2
        cy = y + line_h // 2
        for name in self._refs:
            badge_w = fm.horizontalAdvance(name) + BADGE_H_PAD * 2
            badge_rect = QRect(x, cy - badge_h // 2, badge_w, badge_h)
            painter.setBrush(QBrush(_badge_color(name)))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(badge_rect, BADGE_RADIUS, BADGE_RADIUS)
            painter.setPen(QColor("white"))
            painter.drawText(badge_rect, Qt.AlignCenter, name)
            x += badge_w + BADGE_GAP

        # ── Line 3: Parent(s) ────────────────────────────────────────────────
        y += line_h + PAD
        painter.setPen(QColor(MUTED))
        painter.drawText(PAD, y + fm.ascent(), "Parent: ")
        x = PAD + fm.horizontalAdvance("Parent: ")
        painter.setPen(QColor("white"))
        parents_text = "  ".join(c.parents) if c.parents else "(none)"
        painter.drawText(x, y + fm.ascent(), parents_text)

        painter.end()
```

- [ ] **Step 2: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add git_gui/presentation/widgets/commit_detail.py
git commit -m "feat: add CommitDetailWidget with 3-line metadata display"
```

---

## Task 3: Wire into DiffWidget — detail + message rows

**Files:**
- Modify: `git_gui/presentation/widgets/diff.py`

**Context:** Add `CommitDetailWidget` (Row 1) and a read-only `QPlainTextEdit` for full commit message (Row 2) above the existing file list + diff splitter. `load_commit(oid)` now fetches the `Commit` object and refs, updates both new rows.

- [ ] **Step 1: Replace `git_gui/presentation/widgets/diff.py`**

```python
# git_gui/presentation/widgets/diff.py
from __future__ import annotations
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QTextBlockFormat, QTextCharFormat
from PySide6.QtWidgets import (
    QListView, QPlainTextEdit, QSplitter, QStyledItemDelegate,
    QStyleOptionViewItem, QVBoxLayout, QWidget,
)
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.models.diff_model import DiffModel
from git_gui.presentation.widgets.commit_detail import CommitDetailWidget

_DELTA_BADGE = {
    "modified": ("M", "#1f6feb"),   # blue
    "added":    ("A", "#238636"),   # green
    "deleted":  ("D", "#da3633"),   # red
    "renamed":  ("R", "#f0883e"),   # orange
    "unknown":  ("?", "#8b949e"),   # gray
}

BADGE_SIZE = 20
BADGE_GAP = 6


class _FileDeltaDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        rect = option.rect

        from PySide6.QtWidgets import QStyle
        if option.state & QStyle.State_Selected:
            painter.fillRect(rect, QColor("#264f78"))

        fs = index.data(Qt.UserRole)
        delta = fs.delta if fs else "unknown"
        label, color = _DELTA_BADGE.get(delta, ("?", "#8b949e"))

        badge_x = rect.left() + 4
        badge_y = rect.top() + (rect.height() - BADGE_SIZE) // 2
        badge_rect = QRect(badge_x, badge_y, BADGE_SIZE, BADGE_SIZE)
        painter.setBrush(QBrush(QColor(color)))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(badge_rect, 3, 3)

        painter.setPen(QColor("white"))
        painter.drawText(badge_rect, Qt.AlignCenter, label)

        text_x = badge_x + BADGE_SIZE + BADGE_GAP
        text_rect = QRect(text_x, rect.top(), rect.right() - text_x, rect.height())
        painter.setPen(option.palette.text().color())
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, index.data(Qt.DisplayRole) or "")

        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        return QSize(option.rect.width(), max(BADGE_SIZE + 8, option.fontMetrics.height() + 8))


class DiffWidget(QWidget):
    def __init__(self, queries: QueryBus, commands: CommandBus, parent=None) -> None:
        super().__init__(parent)
        self._queries = queries
        self._current_oid: str | None = None

        # ── Row 1: commit detail (3-line metadata) ──────────────────────────
        self._detail = CommitDetailWidget()

        # ── Row 2: full commit message ──────────────────────────────────────
        self._msg_view = QPlainTextEdit()
        self._msg_view.setReadOnly(True)
        self._msg_view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self._msg_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._msg_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        font = self._msg_view.font()
        font.setFamily("Courier New")
        self._msg_view.setFont(font)

        # ── Row 3: file list ────────────────────────────────────────────────
        self._file_view = QListView()
        self._file_view.setEditTriggers(QListView.NoEditTriggers)
        self._file_view.setItemDelegate(_FileDeltaDelegate(self._file_view))
        self._diff_view = self._make_diff_editor()
        self._diff_model = DiffModel([])
        self._file_view.setModel(self._diff_model)
        self._file_view.selectionModel().currentChanged.connect(
            self._on_file_selected
        )

        # ── Row 4: diff view ────────────────────────────────────────────────
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self._detail)
        splitter.addWidget(self._msg_view)
        splitter.addWidget(self._file_view)
        splitter.addWidget(self._diff_view)
        splitter.setSizes([80, 60, 160, 400])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 0)
        splitter.setStretchFactor(3, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        # Diff render formats
        self._fmt_added = QTextCharFormat()
        self._fmt_added.setForeground(QColor("white"))
        self._fmt_removed = QTextCharFormat()
        self._fmt_removed.setForeground(QColor("white"))
        self._fmt_header = QTextCharFormat()
        self._fmt_header.setForeground(QColor("#58a6ff"))
        self._fmt_default = QTextCharFormat()
        self._fmt_default.setForeground(QColor("white"))

        self._blk_added = QTextBlockFormat()
        self._blk_added.setBackground(QColor(35, 134, 54, 80))
        self._blk_removed = QTextBlockFormat()
        self._blk_removed.setBackground(QColor(248, 81, 73, 80))
        self._blk_default = QTextBlockFormat()

    def load_commit(self, oid: str) -> None:
        self._current_oid = oid

        # Fetch commit detail + refs
        commit = self._queries.get_commit_detail.execute(oid)
        branches = self._queries.get_branches.execute()
        refs = [b.name for b in branches if b.target_oid == oid]
        self._detail.set_commit(commit, refs)

        # Full commit message
        self._msg_view.setPlainText(commit.message)
        doc_h = self._msg_view.document().size().toSize().height() + 10
        self._msg_view.setFixedHeight(min(doc_h, 120))

        # Files
        files = self._queries.get_commit_files.execute(oid)
        self._diff_model.reload(files)
        self._diff_view.clear()
        if files:
            self._file_view.setCurrentIndex(self._diff_model.index(0))

    def _make_diff_editor(self) -> QPlainTextEdit:
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        font = editor.font()
        font.setFamily("Courier New")
        editor.setFont(font)
        return editor

    def _on_file_selected(self, index) -> None:
        if not index.isValid() or self._current_oid is None:
            return
        file_status = self._diff_model.data(index, Qt.UserRole)
        if file_status is None:
            return
        hunks = self._queries.get_file_diff.execute(self._current_oid, file_status.path)
        self._render_diff(hunks)

    @staticmethod
    def _parse_hunk_header(header: str) -> tuple[int, int]:
        import re
        m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", header)
        if m:
            return int(m.group(1)), int(m.group(2))
        return 1, 1

    def _render_diff(self, hunks) -> None:
        self._diff_view.clear()
        cursor = self._diff_view.textCursor()
        for hunk in hunks:
            cursor.setBlockFormat(self._blk_default)
            cursor.setCharFormat(self._fmt_header)
            cursor.insertText(hunk.header + "\n")

            old_line, new_line = self._parse_hunk_header(hunk.header)
            for origin, content in hunk.lines:
                if origin == "+":
                    cursor.setBlockFormat(self._blk_added)
                    cursor.setCharFormat(self._fmt_added)
                    prefix = f"     {new_line:>4}  "
                    new_line += 1
                elif origin == "-":
                    cursor.setBlockFormat(self._blk_removed)
                    cursor.setCharFormat(self._fmt_removed)
                    prefix = f"{old_line:>4}       "
                    old_line += 1
                else:
                    cursor.setBlockFormat(self._blk_default)
                    cursor.setCharFormat(self._fmt_default)
                    prefix = f"{old_line:>4} {new_line:>4}  "
                    old_line += 1
                    new_line += 1
                line = content if content.endswith("\n") else content + "\n"
                cursor.insertText(prefix + line)
        self._diff_view.setTextCursor(cursor)
```

- [ ] **Step 2: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add git_gui/presentation/widgets/diff.py
git commit -m "feat: add commit detail header and message rows to DiffWidget"
```

---

## Self-Review

**Spec coverage:**
- ✅ Row 1 Line 1: Author (with email) + datetime
- ✅ Row 1 Line 2: Full hash + branch/remote/tag badges (colored pills via `_badge_color`)
- ✅ Row 1 Line 3: Parent hash(es)
- ✅ Row 2: Full commit message, read-only, auto-sized
- ✅ Row 1 labels in muted gray, values in white
- ✅ Custom-painted widget for Row 1 (not plain QLabel) to support badge pills
- ✅ New port: `get_commit(oid) -> Commit`
- ✅ New query: `GetCommitDetail`
- ✅ Bus wired
- ✅ DiffWidget.load_commit fetches commit + refs + files

**Placeholder scan:** None.

**Type consistency:** `get_commit(oid: str) -> Commit` consistent across port → repo → query → bus → widget. `CommitDetailWidget.set_commit(commit: Commit, refs: list[str])` called in Task 3 with correct types from Task 1 query. `_badge_color` imported from `ref_badge_delegate` in Task 2, same function used by `commit_info_delegate`.
