# Toolbar Layout + Stash Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the 4 existing toolbar buttons to the left, add a Stash button on the right that confirms before stashing, and hide the Stash button when the working tree is clean.

**Architecture:** Modify the header bar layout in GraphWidget to place existing buttons left and the new Stash button right, separated by a stretch. The graph already knows `is_dirty` from its reload cycle — use that to toggle Stash button visibility. MainWindow handles the confirmation dialog and stash command.

**Tech Stack:** Python, PySide6

---

### Task 1: Rearrange toolbar buttons and add Stash button

**Files:**
- Modify: `git_gui/presentation/widgets/graph.py:73-82` (signals), `126-142` (header bar)

- [ ] **Step 1: Add `stash_requested` signal**

Add to GraphWidget signal declarations (after `fetch_all_requested`):

```python
stash_requested = Signal()
```

- [ ] **Step 2: Rearrange header bar layout and add Stash button**

Replace the header bar block (lines 126-142) with:

```python
        # Header bar with action buttons
        header_bar = QHBoxLayout()
        header_bar.setContentsMargins(4, 4, 4, 4)
        for icon_name, tooltip, signal in [
            ("ic_reload", "Reload (F5)", self.reload_requested),
            ("ic_push", "Push", self.push_requested),
            ("ic_pull", "Pull", self.pull_requested),
            ("ic_fetch", "Fetch All --prune", self.fetch_all_requested),
        ]:
            btn = QPushButton()
            btn.setIcon(QIcon(str(_ARTS / f"{icon_name}.svg")))
            btn.setIconSize(QSize(28, 28))
            btn.setToolTip(tooltip)
            btn.setStyleSheet(_BTN_STYLE)
            btn.clicked.connect(signal.emit)
            header_bar.addWidget(btn)

        header_bar.addStretch()

        self._stash_btn = QPushButton()
        self._stash_btn.setIcon(QIcon(str(_ARTS / "ic_stash.svg")))
        self._stash_btn.setIconSize(QSize(28, 28))
        self._stash_btn.setToolTip("Stash")
        self._stash_btn.setStyleSheet(_BTN_STYLE)
        self._stash_btn.clicked.connect(self.stash_requested.emit)
        self._stash_btn.setVisible(False)
        header_bar.addWidget(self._stash_btn)
```

- [ ] **Step 3: Add `set_stash_visible` method**

Add this method to GraphWidget (e.g. after `clear_selection`):

```python
def set_stash_visible(self, visible: bool) -> None:
    self._stash_btn.setVisible(visible)
```

- [ ] **Step 4: Update visibility in `_on_reload_done`**

In the `_on_reload_done` method, add this line right after `self._loading = False` (line 192):

```python
self._stash_btn.setVisible(is_dirty)
```

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/widgets/graph.py
git commit -m "feat: rearrange toolbar buttons left, add stash button right"
```

---

### Task 2: Wire stash button in MainWindow

**Files:**
- Modify: `git_gui/presentation/main_window.py`

- [ ] **Step 1: Add QMessageBox import**

Add `QMessageBox` to the existing import from `PySide6.QtWidgets`:

```python
from PySide6.QtWidgets import (
    QInputDialog, QMainWindow, QMessageBox, QSplitter, QStackedWidget,
    QVBoxLayout, QWidget,
)
```

- [ ] **Step 2: Connect stash_requested signal**

Add this line in `__init__` after the `fetch_all_requested` connection (after `self._graph.fetch_all_requested.connect(self._on_fetch_all_prune)`):

```python
self._graph.stash_requested.connect(self._on_stash_requested)
```

- [ ] **Step 3: Add `_on_stash_requested` handler**

Add this method to MainWindow (near the other stash handlers):

```python
def _on_stash_requested(self) -> None:
    result = QMessageBox.question(
        self,
        "Stash Changes",
        "Would you like to stash all uncommitted changes?\n\n"
        "This will save your modifications and revert the working directory to a clean state.",
    )
    if result != QMessageBox.Yes:
        return
    branch = self._get_current_branch() or "unknown"
    try:
        self._commands.stash.execute(f"WIP on {branch}")
        self._log_panel.log(f"Stash: WIP on {branch}")
    except Exception as e:
        self._log_panel.expand()
        self._log_panel.log_error(f"Stash — ERROR: {e}")
    self._reload()
```

- [ ] **Step 4: Commit**

```bash
git add git_gui/presentation/main_window.py
git commit -m "feat: wire stash button with confirmation dialog"
```
