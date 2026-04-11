# Repo List Two-Line Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make repositories with the same directory name visually distinguishable in the sidebar by showing the repo name on line 1 and the home-relative path on line 2 via a custom item delegate.

**Architecture:** Add a pure `_display_path` helper and a `_RepoItemDelegate` in `repo_list.py`. The delegate paints repo rows as two lines (name + dim path), uses middle-elision for long paths, and defers to the default painter for header rows. Row height grows from 28 → 40 px for repo rows only.

**Tech Stack:** Python, PySide6 (Qt), pytest, pytest-qt, uv.

**Spec:** `docs/superpowers/specs/2026-04-11-repo-list-two-line-design.md`

---

## File Structure

**Modified:**
- `git_gui/presentation/widgets/repo_list.py` — add `_display_path`, add `_RepoItemDelegate`, install the delegate, drop per-item `setSizeHint` for repo rows.

**New:**
- `tests/presentation/widgets/test_repo_list.py` — unit tests for `_display_path`.

**Theme tokens:** No changes needed. `on_surface_variant` and `on_primary` are already defined in `git_gui/presentation/theme/tokens.py` and both built-in themes.

---

## Task 1: Add `_display_path` helper (TDD)

**Files:**
- Test: `tests/presentation/widgets/test_repo_list.py` (new file)
- Modify: `git_gui/presentation/widgets/repo_list.py`

- [ ] **Step 1: Create the test file with failing tests**

If `tests/presentation/widgets/__init__.py` does not exist, create it as an empty file.

Create `tests/presentation/widgets/test_repo_list.py`:

```python
"""Tests for repo_list helpers."""
from __future__ import annotations
from pathlib import Path

from git_gui.presentation.widgets.repo_list import _display_path


def test_display_path_under_home(monkeypatch, tmp_path):
    fake_home = tmp_path / "user"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    result = _display_path(str(fake_home / "projects" / "GitStack"))

    assert result == "~/projects/GitStack"


def test_display_path_outside_home(monkeypatch, tmp_path):
    fake_home = tmp_path / "user"
    fake_home.mkdir()
    outside = tmp_path / "elsewhere" / "Repo"
    outside.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    result = _display_path(str(outside))

    # Outside-of-home path should come back unchanged (with forward slashes)
    assert "\\" not in result
    assert result.endswith("elsewhere/Repo")
    assert "~" not in result


def test_display_path_home_itself(monkeypatch, tmp_path):
    fake_home = tmp_path / "user"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    result = _display_path(str(fake_home))

    assert result == "~"


def test_display_path_uses_forward_slashes(monkeypatch, tmp_path):
    fake_home = tmp_path / "user"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    result = _display_path(str(fake_home / "a" / "b" / "c"))

    assert "\\" not in result
    assert result == "~/a/b/c"
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `uv run pytest tests/presentation/widgets/test_repo_list.py -v`
Expected: FAIL with `ImportError: cannot import name '_display_path' from 'git_gui.presentation.widgets.repo_list'`.

- [ ] **Step 3: Add the helper to `repo_list.py`**

In `git_gui/presentation/widgets/repo_list.py`, add this module-level function right after the existing `_active_bg()` function (around line 17):

```python
def _display_path(path: str) -> str:
    """Convert an absolute repo path into a display-friendly form.

    Paths under the user's home directory are shortened with ``~``.
    All returned paths use forward slashes, regardless of OS.
    """
    p = Path(path)
    try:
        rel = p.relative_to(Path.home())
    except ValueError:
        return p.as_posix()
    if rel == Path("."):
        return "~"
    return "~/" + rel.as_posix()
```

`Path` is already imported from `pathlib` at the top of the file.

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/presentation/widgets/test_repo_list.py -v`
Expected: All 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/widgets/repo_list.py tests/presentation/widgets/test_repo_list.py
git commit -m "feat(repo_list): add _display_path helper for home-relative paths"
```

---

## Task 2: Add `_RepoItemDelegate`

**Files:**
- Modify: `git_gui/presentation/widgets/repo_list.py`

- [ ] **Step 1: Update imports**

In `git_gui/presentation/widgets/repo_list.py`, update the PySide6 imports. The current `QtGui` import is:

```python
from PySide6.QtGui import QColor, QFont, QPainter, QStandardItem, QStandardItemModel
```

Change it to add `QFontMetrics`:

```python
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QStandardItem, QStandardItemModel
```

Then update the `QtWidgets` import. The current line is:

```python
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton,
    QStyle, QStyleOptionViewItem, QTreeView,
    QVBoxLayout, QWidget,
)
```

Add `QStyledItemDelegate`:

```python
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton,
    QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTreeView,
    QVBoxLayout, QWidget,
)
```

- [ ] **Step 2: Add the delegate class**

Add the `_RepoItemDelegate` class right after the existing `_RepoTree` class (around line 71, before `class RepoListWidget`):

```python
_REPO_ROW_HEIGHT = 40
_ROW_H_PADDING = 8


class _RepoItemDelegate(QStyledItemDelegate):
    """Two-line item delegate for repo rows.

    Line 1: the repo name (Path.name), default font.
    Line 2: _display_path(path), smaller font, dimmer color, middle-elided.

    Header rows (marked with "header" in Qt.UserRole + 1) keep their default
    rendering by deferring to super().paint/sizeHint.
    """

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        if index.data(Qt.UserRole + 1) == "header":
            return super().sizeHint(option, index)
        return QSize(option.rect.width(), _REPO_ROW_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        if index.data(Qt.UserRole + 1) == "header":
            super().paint(painter, option, index)
            return

        path = index.data(Qt.UserRole)
        if not path:
            super().paint(painter, option, index)
            return

        name = Path(path).name
        disp = _display_path(path)
        is_active = bool(index.data(_IS_ACTIVE_ROLE))

        colors = get_theme_manager().current.colors
        name_color = colors.as_qcolor("on_primary") if is_active else colors.as_qcolor("on_surface")
        path_color = colors.as_qcolor("on_surface_variant")

        rect = option.rect
        text_left = rect.left() + _ROW_H_PADDING
        text_right = rect.right() - _ROW_H_PADDING
        text_width = max(0, text_right - text_left)

        # Top half: repo name
        name_font = QFont(option.font)
        if is_active:
            name_font.setBold(True)
        name_metrics = QFontMetrics(name_font)
        name_height = name_metrics.height()
        name_top = rect.top() + (rect.height() // 2) - name_height
        name_rect = QRect(text_left, name_top, text_width, name_height)

        painter.save()
        painter.setFont(name_font)
        painter.setPen(name_color)
        elided_name = name_metrics.elidedText(name, Qt.ElideMiddle, text_width)
        painter.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter, elided_name)

        # Bottom half: display path
        path_font = QFont(option.font)
        path_font.setPointSizeF(max(1.0, path_font.pointSizeF() * 0.85))
        path_metrics = QFontMetrics(path_font)
        path_height = path_metrics.height()
        path_top = name_rect.bottom() + 2
        path_rect = QRect(text_left, path_top, text_width, path_height)

        painter.setFont(path_font)
        painter.setPen(path_color)
        elided_path = path_metrics.elidedText(disp, Qt.ElideMiddle, text_width)
        painter.drawText(path_rect, Qt.AlignLeft | Qt.AlignVCenter, elided_path)

        painter.restore()
```

Also add the `QRect` import at the top — the current `QtCore` import is:

```python
from PySide6.QtCore import QSize, Qt, Signal
```

Change to:

```python
from PySide6.QtCore import QRect, QSize, Qt, Signal
```

- [ ] **Step 3: Install the delegate on `self._tree`**

Find this block in `RepoListWidget.__init__` (around line 122-132):

```python
        # Tree view
        self._tree = _RepoTree()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(False)
        self._tree.setMouseTracking(True)
        self._tree.viewport().setAttribute(Qt.WA_Hover, True)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        self._tree.clicked.connect(self._on_item_clicked)

        self._model = QStandardItemModel()
        self._tree.setModel(self._model)
```

Add the delegate after the `setModel` line:

```python
        self._model = QStandardItemModel()
        self._tree.setModel(self._model)
        self._tree.setItemDelegate(_RepoItemDelegate(self._tree))
```

- [ ] **Step 4: Drop `setSizeHint` for repo rows**

Find `_make_repo_item` (around line 174-187). The current body sets `setSizeHint`:

```python
    def _make_repo_item(self, path: str, kind: str, is_active: bool) -> QStandardItem:
        display_name = Path(path).name
        item = QStandardItem(display_name)
        item.setEditable(False)
        item.setToolTip(path)
        item.setData(path, Qt.UserRole)
        item.setData(kind, Qt.UserRole + 1)
        item.setSizeHint(QSize(0, _ROW_HEIGHT))
        if is_active:
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            item.setData(True, _IS_ACTIVE_ROLE)
        return item
```

Remove the `item.setSizeHint(...)` line so the delegate controls height:

```python
    def _make_repo_item(self, path: str, kind: str, is_active: bool) -> QStandardItem:
        display_name = Path(path).name
        item = QStandardItem(display_name)
        item.setEditable(False)
        item.setToolTip(path)
        item.setData(path, Qt.UserRole)
        item.setData(kind, Qt.UserRole + 1)
        if is_active:
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            item.setData(True, _IS_ACTIVE_ROLE)
        return item
```

Leave the header-row `setSizeHint` calls (at lines ~153 and ~166) untouched — headers still explicitly set their height.

- [ ] **Step 5: Verify import and smoke-check**

Run: `uv run python -c "from git_gui.presentation.widgets.repo_list import RepoListWidget, _RepoItemDelegate, _display_path; print('ok')"`
Expected: `ok`

- [ ] **Step 6: Run full suite**

Run: `uv run pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add git_gui/presentation/widgets/repo_list.py
git commit -m "feat(repo_list): render repos as two-line entries via custom delegate"
```

---

## Task 3: Manual acceptance

- [ ] **Step 1: Launch the app**

Run: `uv run python main.py`

- [ ] **Step 2: Verify disambiguation**

Open two repositories whose directories share a name but live in different parent directories (e.g. `~/projects/GitStack` and `~/work/GitStack`). Verify both are distinguishable at a glance: each row shows the repo name on top and `~/projects/GitStack` / `~/work/GitStack` below in smaller dim text.

- [ ] **Step 3: Verify tooltip fallback**

Hover over a repo row. The tooltip should still show the full untruncated absolute path.

- [ ] **Step 4: Verify middle-elision**

Shrink the main window so the sidebar becomes narrow. The second line should middle-elide with `…` — the start (`~/...`) and the end (the directory containing the repo) should both remain visible.

- [ ] **Step 5: Verify active-repo styling**

Switch between repos. The active repo's name should be bold and rendered in `on_primary` over the primary-color active background (current behavior). The secondary path line should stay dim in both active and inactive states.

- [ ] **Step 6: Verify headers and collapsing**

Confirm that the `OPEN` and `RECENT` section headers still look unchanged and collapse/expand correctly.

- [ ] **Step 7: Verify context menu and clicks**

Right-click a repo row — the context menu should still appear with the existing items. Click a recent repo — it should open as before. Click an open repo — it should switch as before.

- [ ] **Step 8: Commit any follow-up fixes**

If manual testing reveals issues, fix and commit with descriptive messages.

---

## Out of Scope

- Branch name / dirty indicator on repo rows (separate follow-up).
- Title bar or dialog display changes (already show full path).
- Repo metadata stored in the repo store (path alone is sufficient for this change).
