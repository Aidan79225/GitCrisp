# Operation Log Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a collapsible log panel at the bottom of the main window that shows git operations with timestamps, auto-expanding for remote operations.

**Architecture:** A new `LogPanel` widget provides `log()` / `log_error()` / `expand()` methods. `MainWindow` wraps remote commands with start/end logging and logs commits. `WorkingTreeWidget` emits a `commit_completed` signal with the message.

**Tech Stack:** Python 3.13, PySide6 6.11

---

## File Map

| File | Change |
|------|--------|
| `git_gui/presentation/widgets/log_panel.py` | New — collapsible log panel widget |
| `git_gui/presentation/widgets/working_tree.py` | Add `commit_completed` signal |
| `git_gui/presentation/main_window.py` | Add LogPanel, wrap operations with logging |

---

## Task 1: LogPanel widget

**Files:**
- Create: `git_gui/presentation/widgets/log_panel.py`

**Context:** A collapsible panel with a clickable header and a read-only text body. Default collapsed. Provides `log(msg)`, `log_error(msg)`, `expand()`, `collapse()` methods. No tests — presentation-only.

- [ ] **Step 1: Create `git_gui/presentation/widgets/log_panel.py`**

```python
# git_gui/presentation/widgets/log_panel.py
from __future__ import annotations
from datetime import datetime
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget


class LogPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._expanded = False

        self._header = QLabel("▶ Operations Log")
        self._header.setStyleSheet(
            "padding: 4px 8px; background: #1e1e1e; color: #cccccc; font-weight: bold;"
        )
        self._header.setCursor(Qt.PointingHandCursor)
        self._header.mousePressEvent = lambda _: self.toggle()

        self._body = QPlainTextEdit()
        self._body.setReadOnly(True)
        self._body.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._body.setMaximumHeight(150)
        font = self._body.font()
        font.setFamily("Courier New")
        self._body.setFont(font)
        self._body.setVisible(False)

        self._fmt_default = QTextCharFormat()
        self._fmt_default.setForeground(QColor("#cccccc"))
        self._fmt_error = QTextCharFormat()
        self._fmt_error.setForeground(QColor("#f85149"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header)
        layout.addWidget(self._body)

    def log(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._append(f"[{ts}] {message}", self._fmt_default)

    def log_error(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._append(f"[{ts}] {message}", self._fmt_error)

    def expand(self) -> None:
        self._expanded = True
        self._body.setVisible(True)
        self._header.setText("▼ Operations Log")

    def collapse(self) -> None:
        self._expanded = False
        self._body.setVisible(False)
        self._header.setText("▶ Operations Log")

    def toggle(self) -> None:
        if self._expanded:
            self.collapse()
        else:
            self.expand()

    def _append(self, text: str, fmt: QTextCharFormat) -> None:
        cursor = self._body.textCursor()
        cursor.movePosition(QTextCursor.End)
        if self._body.document().characterCount() > 1:
            cursor.insertText("\n", fmt)
        cursor.insertText(text, fmt)
        self._body.setTextCursor(cursor)
        self._body.ensureCursorVisible()
```

- [ ] **Step 2: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all 83 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add git_gui/presentation/widgets/log_panel.py
git commit -m "feat: add collapsible LogPanel widget"
```

---

## Task 2: Wire LogPanel into MainWindow + commit signal

**Files:**
- Modify: `git_gui/presentation/widgets/working_tree.py`
- Modify: `git_gui/presentation/main_window.py`

**Context:** Add `commit_completed = Signal(str)` to `WorkingTreeWidget` (emits the commit message). In `MainWindow`, add `LogPanel` below the main splitter. Wrap push/pull/fetch with start/end/error logging. Connect commit signal to log.

- [ ] **Step 1: Add `commit_completed` signal to `WorkingTreeWidget`**

In `git_gui/presentation/widgets/working_tree.py`, add a new signal alongside `reload_requested`:

```python
    reload_requested = Signal()
    commit_completed = Signal(str)  # emits first line of commit message
```

Update `_on_commit` to emit it:

```python
    def _on_commit(self) -> None:
        msg = self._msg_edit.toPlainText().strip()
        if not msg:
            return
        self._commands.create_commit.execute(msg)
        first_line = msg.split("\n")[0]
        self._msg_edit.clear()
        self.commit_completed.emit(first_line)
        self.reload_requested.emit()
        self.reload()
```

- [ ] **Step 2: Replace `git_gui/presentation/main_window.py`**

```python
# git_gui/presentation/main_window.py
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QSplitter, QStackedWidget, QToolBar, QVBoxLayout, QWidget,
)
from git_gui.domain.entities import WORKING_TREE_OID
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.widgets.diff import DiffWidget
from git_gui.presentation.widgets.graph import GraphWidget
from git_gui.presentation.widgets.log_panel import LogPanel
from git_gui.presentation.widgets.sidebar import SidebarWidget
from git_gui.presentation.widgets.working_tree import WorkingTreeWidget


class MainWindow(QMainWindow):
    def __init__(self, queries: QueryBus, commands: CommandBus, repo_path: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"git gui — {repo_path}")
        self.resize(1400, 800)

        self._queries = queries
        self._commands = commands
        self._sidebar = SidebarWidget(queries, commands)
        self._graph = GraphWidget(queries, commands)
        self._diff = DiffWidget(queries, commands)
        self._working_tree = WorkingTreeWidget(queries, commands)
        self._log_panel = LogPanel()

        self._right_stack = QStackedWidget()
        self._right_stack.addWidget(self._diff)           # index 0: commit mode
        self._right_stack.addWidget(self._working_tree)    # index 1: working tree

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._sidebar)
        splitter.addWidget(self._graph)
        splitter.addWidget(self._right_stack)
        splitter.setSizes([220, 230, 950])

        # Main layout: splitter on top, log panel at bottom
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(splitter, 1)
        central_layout.addWidget(self._log_panel, 0)

        self._toolbar = QToolBar("Main")
        self._reload_action = QAction("Reload", self)
        self._reload_action.setShortcut(QKeySequence(Qt.Key_F5))
        self._reload_action.triggered.connect(self._reload)
        self._toolbar.addAction(self._reload_action)

        self._push_action = QAction("Push", self)
        self._push_action.triggered.connect(self._on_push)
        self._toolbar.addAction(self._push_action)

        self._pull_action = QAction("Pull", self)
        self._pull_action.triggered.connect(self._on_pull)
        self._toolbar.addAction(self._pull_action)

        self._fetch_all_action = QAction("Fetch All -p", self)
        self._fetch_all_action.triggered.connect(self._on_fetch_all_prune)
        self._toolbar.addAction(self._fetch_all_action)

        self.addToolBar(self._toolbar)
        self.setCentralWidget(central)

        # Wire cross-widget signals
        self._graph.commit_selected.connect(self._on_commit_selected)
        self._working_tree.reload_requested.connect(self._reload)
        self._working_tree.commit_completed.connect(
            lambda msg: self._log_panel.log(f'Commit: "{msg}"')
        )
        self._sidebar.branch_checkout_requested.connect(self._on_branch_changed)
        self._sidebar.branch_merge_requested.connect(
            lambda b: (commands.merge.execute(b), self._reload()))
        self._sidebar.branch_rebase_requested.connect(
            lambda b: (commands.rebase.execute(b), self._reload()))
        self._sidebar.branch_delete_requested.connect(
            lambda b: (commands.delete_branch.execute(b), self._reload()))
        self._sidebar.fetch_requested.connect(
            lambda r: self._run_remote_op(f"Fetch {r}", lambda: commands.fetch.execute(r)))
        self._sidebar.branch_push_requested.connect(
            lambda b: self._run_remote_op(f"Push origin/{b}", lambda: commands.push.execute("origin", b)))

        self._reload()

    def _on_commit_selected(self, oid: str) -> None:
        if oid == WORKING_TREE_OID:
            self._right_stack.setCurrentIndex(1)
            self._working_tree.reload()
        else:
            self._right_stack.setCurrentIndex(0)
            self._diff.load_commit(oid)

    def _reload(self) -> None:
        self._sidebar.reload()
        self._graph.reload()

    def _on_branch_changed(self, branch: str) -> None:
        self._reload()

    def _get_current_branch(self) -> str | None:
        branches = self._queries.get_branches.execute()
        for b in branches:
            if b.is_head and not b.is_remote:
                return b.name
        return None

    def _run_remote_op(self, name: str, fn) -> None:
        self._log_panel.expand()
        self._log_panel.log(f"{name} — started...")
        try:
            fn()
            self._log_panel.log(f"{name} — done")
        except Exception as e:
            self._log_panel.log_error(f"{name} — ERROR: {e}")
        self._reload()

    def _on_push(self) -> None:
        branch = self._get_current_branch()
        if branch:
            self._run_remote_op(
                f"Push origin/{branch}",
                lambda: self._commands.push.execute("origin", branch),
            )

    def _on_pull(self) -> None:
        branch = self._get_current_branch()
        if branch:
            self._run_remote_op(
                f"Pull origin/{branch}",
                lambda: self._commands.pull.execute("origin", branch),
            )

    def _on_fetch_all_prune(self) -> None:
        self._run_remote_op(
            "Fetch --all --prune",
            lambda: self._commands.fetch_all_prune.execute(),
        )
```

- [ ] **Step 3: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all 83 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add git_gui/presentation/widgets/working_tree.py git_gui/presentation/widgets/log_panel.py git_gui/presentation/main_window.py
git commit -m "feat: wire LogPanel into MainWindow with operation logging"
```

---

## Self-Review

**Spec coverage:**
- ✅ Collapsible panel at bottom, default collapsed
- ✅ Auto-expand on remote operations (push/pull/fetch)
- ✅ Click header to toggle
- ✅ Timestamp format `[HH:MM:SS]`
- ✅ Commit logged as `Commit: "message"`
- ✅ Remote ops: start + done/error
- ✅ Errors in red
- ✅ In-memory only
- ✅ `commit_completed` signal from WorkingTreeWidget
- ✅ Sidebar fetch/push also logged via `_run_remote_op`

**Placeholder scan:** None.

**Type consistency:** `log(str)`, `log_error(str)`, `expand()`, `collapse()`, `toggle()` consistent between Task 1 definition and Task 2 usage. `commit_completed = Signal(str)` emitted in Task 2 Step 1, connected in Task 2 Step 2.
