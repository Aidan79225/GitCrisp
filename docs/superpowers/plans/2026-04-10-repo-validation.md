# Repo Path Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent crashes when opening a directory that is not a git repository, by validating paths at every entry point.

**Architecture:** Add `_is_git_repo()` validation using `pygit2.discover_repository()` at the two entry points where repo paths enter the system: `main.py` (startup) and `repo_list.py` (sidebar "Add" button). Invalid stored paths get pruned; invalid picker selections show an error and re-open the picker.

**Tech Stack:** Python, pygit2, PySide6 (QMessageBox, QFileDialog)

---

### Task 1: Add validation to `main.py`

**Files:**
- Modify: `main.py:1-36`
- Test: `tests/test_main_validation.py` (create)

- [ ] **Step 1: Write the failing test for `_is_git_repo`**

Create `tests/test_main_validation.py`:

```python
import pygit2
import pytest
from pathlib import Path


def _is_git_repo(path: str) -> bool:
    return pygit2.discover_repository(path) is not None


class TestIsGitRepo:
    def test_returns_true_for_valid_repo(self, tmp_path):
        pygit2.init_repository(str(tmp_path))
        assert _is_git_repo(str(tmp_path)) is True

    def test_returns_false_for_plain_directory(self, tmp_path):
        assert _is_git_repo(str(tmp_path)) is False

    def test_returns_false_for_nonexistent_path(self, tmp_path):
        assert _is_git_repo(str(tmp_path / "nope")) is False
```

- [ ] **Step 2: Run test to verify it passes** (these test a standalone copy of the function)

Run: `uv run pytest tests/test_main_validation.py -v`
Expected: 3 PASS

- [ ] **Step 3: Write the failing test for `_find_valid_repo` pruning non-git dirs**

Add to `tests/test_main_validation.py`:

```python
from git_gui.infrastructure.repo_store import JsonRepoStore


class TestFindValidRepoPruning:
    def test_prunes_non_git_directory_from_store(self, tmp_path):
        """A stored path that exists as a dir but is not a git repo gets pruned."""
        plain_dir = tmp_path / "not_a_repo"
        plain_dir.mkdir()

        store_path = tmp_path / "repos.json"
        store = JsonRepoStore(store_path)
        store.load()
        store.add_open(str(plain_dir))
        store.save()

        # Re-import to use the real function from main
        from main import _find_valid_repo

        result = _find_valid_repo(store)
        assert result is None
        assert str(plain_dir) not in store.get_open_repos()

    def test_returns_valid_git_repo(self, tmp_path):
        """A stored path that is a valid git repo is returned."""
        repo_dir = tmp_path / "real_repo"
        repo_dir.mkdir()
        pygit2.init_repository(str(repo_dir))

        store_path = tmp_path / "repos.json"
        store = JsonRepoStore(store_path)
        store.load()
        store.add_open(str(repo_dir))
        store.save()

        from main import _find_valid_repo

        result = _find_valid_repo(store)
        assert result == str(repo_dir)
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/test_main_validation.py::TestFindValidRepoPruning -v`
Expected: FAIL — `_find_valid_repo` currently accepts non-git directories

- [ ] **Step 5: Implement the changes in `main.py`**

Add `import pygit2` and `from PySide6.QtWidgets import QMessageBox` to imports. Add the helper function. Update `_pick_repo` and `_find_valid_repo`:

```python
import sys
import pygit2
from pathlib import Path
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from git_gui.infrastructure.pygit2_repo import Pygit2Repository
from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.main_window import MainWindow
from git_gui.presentation.theme import ThemeManager, set_theme_manager


def _is_git_repo(path: str) -> bool:
    return pygit2.discover_repository(path) is not None


def _pick_repo() -> str:
    while True:
        dialog = QFileDialog()
        dialog.setWindowTitle("Open Repository")
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setOption(QFileDialog.ShowDirsOnly, True)
        if dialog.exec() != QFileDialog.Accepted:
            return ""
        dirs = dialog.selectedFiles()
        if not dirs:
            return ""
        path = dirs[0]
        if _is_git_repo(path):
            return path
        QMessageBox.warning(
            None,
            "Not a Git Repository",
            "The selected folder is not a Git repository.\n"
            "Please choose a folder that contains a Git repository.",
        )


def _find_valid_repo(repo_store: JsonRepoStore) -> str | None:
    """Return the first valid repo path from active or open list, pruning invalid ones."""
    active = repo_store.get_active()
    if active and Path(active).is_dir() and _is_git_repo(active):
        return active

    for path in list(repo_store.get_open_repos()):
        if Path(path).is_dir() and _is_git_repo(path):
            repo_store.set_active(path)
            return path
        repo_store.close_repo(path)

    repo_store.save()
    return None
```

The `main()` function stays unchanged.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_main_validation.py -v`
Expected: All 5 PASS

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_main_validation.py
git commit -m "fix: validate git repo at startup, prevent crash on non-git directory"
```

---

### Task 2: Add validation to repo list "Add" button

**Files:**
- Modify: `git_gui/presentation/widgets/repo_list.py:1-11, 220-228`

- [ ] **Step 1: Update `_on_add_clicked` with validation loop**

In `git_gui/presentation/widgets/repo_list.py`, add `QMessageBox` to the existing PySide6 import and add `import pygit2` at the top. Then replace `_on_add_clicked`:

Add `QMessageBox` to the import on line 6-9:
```python
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton,
    QStyle, QStyleOptionViewItem, QTreeView,
    QVBoxLayout, QWidget,
)
```

Add after the existing imports (line 12):
```python
import pygit2
```

Replace `_on_add_clicked` (lines 220-228):
```python
def _on_add_clicked(self) -> None:
    while True:
        dialog = QFileDialog(self)
        dialog.setWindowTitle("Open Repository")
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setOption(QFileDialog.ShowDirsOnly, True)
        if dialog.exec() != QFileDialog.Accepted:
            return
        dirs = dialog.selectedFiles()
        if not dirs:
            return
        path = dirs[0]
        if pygit2.discover_repository(path) is not None:
            self.repo_open_requested.emit(path)
            return
        QMessageBox.warning(
            self,
            "Not a Git Repository",
            "The selected folder is not a Git repository.\n"
            "Please choose a folder that contains a Git repository.",
        )
```

- [ ] **Step 2: Run full test suite to verify no regressions**

Run: `uv run pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add git_gui/presentation/widgets/repo_list.py
git commit -m "fix: validate git repo in sidebar Add button, show error for non-git dirs"
```
