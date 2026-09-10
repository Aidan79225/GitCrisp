# Per-component expand/collapse for commit message and file diff blocks

## Context

The commit detail panel grows linearly with the size of the commit:
the message can be many paragraphs, and a commit touching dozens of
files renders one diff block per file. Today the user has no way to
hide either — they scroll. The fix is per-component expand/collapse
toggles: one on the commit message, one on each file's diff block.

## Decisions (per brainstorming Q&A)

- **Per-component scope**, not a global expand-all/collapse-all.
- **File collapsed → only the file header row visible** (just the
  `📄 path` line; all hunks hidden).
- **Message collapsed → only the subject line (first line) visible**.
- **Default state: all expanded** (today's behavior). No state
  persistence across commits or restarts.

## Architecture

Three pieces, each small and reusable:

1. A new tiny widget `_CollapseToggle` (chevron QToolButton) in a
   new file. Both call sites reuse it.
2. `diff_block._build_skeleton_block` adds a `_CollapseToggle` to
   the header row and wires it to hide non-header children of the
   `inner` layout.
3. `diff.py` wraps `_msg_view` in a panel with a slim header strip
   that holds a `_CollapseToggle` + a "Message" label; toggling
   shrinks the QPlainTextEdit's fixed height down to one line.

## Component 1: `_CollapseToggle`

New file: `git_gui/presentation/widgets/_collapse_toggle.py`.

```python
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QToolButton


class _CollapseToggle(QToolButton):
    """Down/right chevron toggle.

    Emits state_changed(True) when expanded, False when collapsed.
    Initial state expanded by default. Compact (16×16) and auto-raise
    so it sits flush in a header row.
    """

    state_changed = Signal(bool)

    def __init__(self, expanded: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(expanded)
        self.setAutoRaise(True)
        self.setFixedSize(QSize(16, 16))
        self.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.setCursor(Qt.PointingHandCursor)
        self.toggled.connect(self._on_toggle)

    def _on_toggle(self, checked: bool) -> None:
        self.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        self.state_changed.emit(checked)

    def is_expanded(self) -> bool:
        return self.isChecked()
```

## Component 2: per-file hunks toggle

Modify `git_gui/presentation/widgets/diff_block.py`. In
`_build_skeleton_block`, the existing `header_row_layout` is:

```python
header_row_layout.setSpacing(4)
label_text = f"\U0001f4c4 {path}"
if on_header_clicked is not None:
    header_label = _ClickableLabel(label_text, on_header_clicked)
else:
    header_label = QLabel(label_text)
header_label.setStyleSheet(_header_style())
header_row_layout.addWidget(header_label)
header_row_layout.addStretch()
```

Insert a `_CollapseToggle` before `header_label`:

```python
toggle = _CollapseToggle(expanded=True)
header_row_layout.addWidget(toggle)
header_row_layout.addWidget(header_label)
header_row_layout.addStretch()
```

Wire the toggle to hide non-header children of `inner` when
collapsed:

```python
def _set_expanded(expanded: bool) -> None:
    for i in range(1, inner.count()):
        item = inner.itemAt(i)
        w = item.widget() if item else None
        if w is not None:
            w.setVisible(expanded)
toggle.state_changed.connect(_set_expanded)
```

Index 0 of `inner` is the header row itself, which always stays
visible. Indices ≥ 1 are the hunk widgets added later by the
realize/skeleton flow.

The frame already has `setSizePolicy(Preferred, Maximum)`, so the
overall frame shrinks to fit just the visible header when collapsed.

## Component 3: commit message toggle

Modify `git_gui/presentation/widgets/diff.py`. Currently:

```python
self._msg_view = QPlainTextEdit()
# ... configure ...
scroll_content_layout.addWidget(self._msg_view)
```

Wrap in a panel:

```python
self._msg_view = QPlainTextEdit()
# ... existing configuration ...

self._msg_panel = QWidget()
msg_layout = QVBoxLayout(self._msg_panel)
msg_layout.setContentsMargins(0, 0, 0, 0)
msg_layout.setSpacing(2)

msg_header = QHBoxLayout()
msg_header.setContentsMargins(0, 0, 0, 0)
msg_header.setSpacing(4)
self._msg_toggle = _CollapseToggle(expanded=True)
msg_header.addWidget(self._msg_toggle)
msg_header_label = QLabel("Message")
msg_header_label.setStyleSheet("color: ...")  # use _muted from theme
msg_header.addWidget(msg_header_label)
msg_header.addStretch()

msg_layout.addLayout(msg_header)
msg_layout.addWidget(self._msg_view)

self._msg_full_h: int = 0
self._msg_collapsed_h: int = 0
self._msg_toggle.state_changed.connect(self._on_msg_toggle)

scroll_content_layout.addWidget(self._msg_panel)  # was: addWidget(self._msg_view)
```

Replace each `self._msg_view.setVisible(not empty)` call site with
`self._msg_panel.setVisible(not empty)` (so the empty state hides
the panel, not just the QPlainTextEdit).

Update `load_commit` to remember both heights:

```python
self._msg_view.setPlainText(msg)
line_count = msg.count("\n") + 1
line_h = self._msg_view.fontMetrics().lineSpacing()
doc_margin = self._msg_view.document().documentMargin() * 2
self._msg_full_h = int(line_count * line_h + doc_margin)
self._msg_collapsed_h = int(line_h + doc_margin)
self._msg_view.setFixedHeight(
    self._msg_full_h if self._msg_toggle.is_expanded() else self._msg_collapsed_h
)
```

The toggle handler:

```python
def _on_msg_toggle(self, expanded: bool) -> None:
    self._msg_view.setFixedHeight(
        self._msg_full_h if expanded else self._msg_collapsed_h
    )
```

When collapsed, the QPlainTextEdit clips to a single line — the
subject. Vertical scrollbar is already disabled; the body stays in
the document but is not visible.

## What stays the same

- The unified scroll area's overall layout.
- `_StickyPinController`'s pin/unpin logic — the threshold is based
  on `_flow_slot.geometry().top()`, which depends on `_msg_view`'s
  height. The threshold gets recomputed on `recompute_threshold()`,
  so manual collapse may slightly shift it but the controller
  re-evaluates on scroll. Acceptable.
- File navigator (`FileNavigatorWidget`), reset / restore selection
  flows, and lazy-loading of diff hunks.

## Edge cases

- **Empty state.** When no commit is loaded, `_msg_panel` and
  `_diff_container` stay hidden via `_set_empty_state(True)`.
- **Re-loading the same commit.** `_msg_full_h` and
  `_msg_collapsed_h` are recomputed every `load_commit`. The
  toggle's state is preserved across loads (per-session, per-
  panel). User who collapses the message and then switches commits
  keeps the message collapsed — acceptable since this is one
  toggle, not per-commit state.
- **Collapsed file with skeleton not yet realized.** When the user
  collapses a file before its hunks have been lazily realized,
  hiding indices ≥ 1 hides the skeleton placeholder. The realizer
  still runs when the file later scrolls into view, but its added
  widgets land in the (hidden) layout — they stay hidden until the
  user expands. No special handling required.

## Tests

- **`tests/presentation/widgets/test_collapse_toggle.py`** (new) —
  click cycles arrow type and emits `state_changed` with correct
  boolean.
- **`tests/presentation/widgets/test_diff_block.py`** (or sibling)
  — after building a skeleton block and toggling collapsed, only
  the header row is visible inside `inner`.
- **`tests/presentation/widgets/test_diff_widget.py`** — after
  loading a commit and toggling the message collapse, `_msg_view`
  height ≈ one line of text + margin.

## Files

- **Create:** `git_gui/presentation/widgets/_collapse_toggle.py`
- **Create:** `tests/presentation/widgets/test_collapse_toggle.py`
- **Modify:** `git_gui/presentation/widgets/diff_block.py`
- **Modify:** `git_gui/presentation/widgets/diff.py`
- **Modify:** `tests/presentation/widgets/test_diff_widget.py`
- **Possibly modify:** `tests/presentation/widgets/test_diff_block.py`
  if it exists — otherwise add to the existing diff-widget test file.

## Verification

**Automated:**
```
uv run pytest tests/presentation/widgets/test_collapse_toggle.py -v
uv run pytest tests/presentation/widgets/ -v
uv run pytest tests/ -q
```

**Manual:**
1. `uv run python main.py`. Open a commit with a multi-paragraph
   message and several files.
2. Click the chevron in the message header. Message collapses to
   the subject line. Click again — full body returns.
3. Click the chevron in any file's header row. The file's hunks
   collapse; only the `📄 path` line remains. Click again —
   hunks return.
4. Toggle multiple files collapsed/expanded. Each operates
   independently.
5. Switch to a different commit. Files re-render expanded by
   default; the message panel preserves its toggle state across
   the load (acceptable per spec).
