# Operation Log Panel — Design Spec
_Date: 2026-04-04_

## Overview

Add a collapsible log panel at the bottom of the main window that displays git operations (commit, push, pull, fetch) with timestamps. Remote operations show start/end messages. Errors are displayed in red. The panel auto-expands when a remote operation begins.

---

## Layout

```
┌─────────────────────────────────────────────────┐
│  Sidebar  │  Graph  │  Diff/WorkingTree         │
│           │         │                            │
├───────────┴─────────┴────────────────────────────┤
│ ▼ Operations Log                                 │
│ [14:32:01] Commit: "feat: add button"            │
│ [14:33:15] Push origin/main — started...         │
│ [14:33:18] Push origin/main — done               │
│ [14:35:02] Fetch --all --prune — started...      │
│ [14:35:05] Fetch --all --prune — done            │
│ [14:35:10] Push origin/main — ERROR: rejected    │
└──────────────────────────────────────────────────┘
```

- Panel spans full window width, below the main horizontal splitter
- Default state: collapsed (only header bar visible, ~25px)
- Auto-expands when a remote operation (push/pull/fetch) starts
- Click header to toggle collapse/expand
- Header shows ▶ when collapsed, ▼ when expanded

---

## LogPanel Widget — `log_panel.py`

A `QWidget` with two parts: a clickable header and a read-only text body.

### Header
- `QLabel` displaying "▶ Operations Log" (collapsed) or "▼ Operations Log" (expanded)
- Click toggles collapse/expand

### Body
- `QPlainTextEdit`, read-only, monospace font
- Auto-scrolls to bottom on new entries
- Default height when expanded: ~150px

### Public API

```python
def log(self, message: str) -> None:
    """Append a timestamped line in default color."""

def log_error(self, message: str) -> None:
    """Append a timestamped line in red."""

def expand(self) -> None:
    """Show the text body."""

def collapse(self) -> None:
    """Hide the text body."""
```

### Log Entry Format

- Timestamp prefix: `[HH:MM:SS]`
- Commit: `[14:32:01] Commit: "first line of message"`
- Remote start: `[14:33:15] Push origin/main — started...`
- Remote end: `[14:33:18] Push origin/main — done`
- Error: `[14:35:10] Push origin/main — ERROR: <error message>` (red text)

---

## MainWindow Changes — `main_window.py`

### Layout
- Replace the current `setCentralWidget(splitter)` with a `QVBoxLayout` containing the horizontal splitter and the `LogPanel` below it.

### Logging wrapper

Add a helper method to wrap remote operations:

```python
def _run_remote_op(self, name: str, fn: callable) -> None:
    self._log_panel.expand()
    self._log_panel.log(f"{name} — started...")
    try:
        fn()
        self._log_panel.log(f"{name} — done")
    except Exception as e:
        self._log_panel.log_error(f"{name} — ERROR: {e}")
```

### Operations to log

| Operation | Log format | Auto-expand |
|-----------|-----------|-------------|
| Commit | `Commit: "message"` | No |
| Push | start + done/error | Yes |
| Pull | start + done/error | Yes |
| Fetch | start + done/error | Yes |
| Fetch All -p | start + done/error | Yes |

Commit logging is added to `WorkingTreeWidget._on_commit` via a new signal `commit_completed(str)` that MainWindow connects to the log panel. Alternatively, MainWindow can log after `working_tree.reload_requested` fires — but a dedicated signal with the message text is cleaner.

---

## Files Changed

| File | Change |
|------|--------|
| `git_gui/presentation/widgets/log_panel.py` | New — collapsible log panel widget |
| `git_gui/presentation/main_window.py` | Add LogPanel, wrap push/pull/fetch with logging |
| `git_gui/presentation/widgets/working_tree.py` | Add `commit_completed` signal with message text |

No domain, infrastructure, or bus layer changes.
