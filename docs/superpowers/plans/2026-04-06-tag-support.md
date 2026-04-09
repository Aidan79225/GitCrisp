# Tag Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add tag support across the UI — sidebar listing, badge display on commit graph and commit detail, create/delete/push operations.

**Architecture:** Add a `Tag` entity and wire it through all Clean Architecture layers (domain → application → infrastructure → presentation). Tags integrate into the existing `refs` dict pattern used by the graph model, so badges render automatically. New `CreateTagDialog` for the graph right-click menu. Sidebar gets a TAGS section with click-to-scroll and context menu.

**Tech Stack:** Python 3.13, PySide6, pygit2

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `git_gui/domain/entities.py` | Modify | Add `Tag` dataclass |
| `git_gui/domain/ports.py` | Modify | Add tag methods to `IRepositoryReader` and `IRepositoryWriter` |
| `git_gui/application/queries.py` | Modify | Add `GetTags` query |
| `git_gui/application/commands.py` | Modify | Add `CreateTag`, `DeleteTag`, `PushTag` commands |
| `git_gui/infrastructure/pygit2_repo.py` | Modify | Implement `get_tags`, `create_tag`, `delete_tag`, `push_tag` |
| `git_gui/presentation/bus.py` | Modify | Add tag queries/commands to buses |
| `git_gui/presentation/widgets/ref_badge_delegate.py` | Modify | Add tag badge color + display name stripping |
| `git_gui/presentation/widgets/graph.py` | Modify | Fetch tags in reload, add to refs dict, add context menu item + signal |
| `git_gui/presentation/widgets/sidebar.py` | Modify | Add TAGS section, tag signals, tag context menu |
| `git_gui/presentation/widgets/create_tag_dialog.py` | Create | Dialog for creating tags |
| `git_gui/presentation/main_window.py` | Modify | Wire tag signals, handle create/delete/push tag |
| `tests/infrastructure/test_reads.py` | Modify | Add tag read tests |
| `tests/infrastructure/test_writes.py` | Modify | Add tag write tests |

---

### Task 1: Add Tag entity and ports

**Files:**
- Modify: `git_gui/domain/entities.py`
- Modify: `git_gui/domain/ports.py`
- Test: `tests/domain/test_entities.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/domain/test_entities.py`:

```python
from git_gui.domain.entities import Tag
from datetime import datetime, timezone


def test_tag_lightweight():
    tag = Tag(name="v1.0.0", target_oid="abc123", is_annotated=False,
              message=None, tagger=None, timestamp=None)
    assert tag.name == "v1.0.0"
    assert tag.target_oid == "abc123"
    assert tag.is_annotated is False
    assert tag.message is None


def test_tag_annotated():
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    tag = Tag(name="v2.0.0", target_oid="def456", is_annotated=True,
              message="Release 2.0", tagger="Alice <alice@example.com>", timestamp=ts)
    assert tag.is_annotated is True
    assert tag.message == "Release 2.0"
    assert tag.tagger == "Alice <alice@example.com>"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/domain/test_entities.py::test_tag_lightweight -v`
Expected: FAIL — `ImportError: cannot import name 'Tag'`

- [ ] **Step 3: Add Tag entity**

Add to `git_gui/domain/entities.py` after the `Stash` dataclass:

```python
@dataclass
class Tag:
    name: str
    target_oid: str
    is_annotated: bool
    message: str | None
    tagger: str | None
    timestamp: datetime | None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/domain/test_entities.py -v`
Expected: PASS

- [ ] **Step 5: Add tag methods to ports**

In `git_gui/domain/ports.py`, add `Tag` to the import:

```python
from git_gui.domain.entities import Branch, Commit, FileStatus, Hunk, Stash, Tag
```

Add to `IRepositoryReader` protocol:

```python
    def get_tags(self) -> list[Tag]: ...
```

Add to `IRepositoryWriter` protocol:

```python
    def create_tag(self, name: str, oid: str, message: str | None = None) -> None: ...
    def delete_tag(self, name: str) -> None: ...
    def push_tag(self, remote: str, name: str) -> None: ...
```

- [ ] **Step 6: Commit**

```bash
git add git_gui/domain/entities.py git_gui/domain/ports.py tests/domain/test_entities.py
git commit -m "feat: add Tag entity and port methods"
```

---

### Task 2: Implement tag operations in infrastructure

**Files:**
- Modify: `git_gui/infrastructure/pygit2_repo.py`
- Test: `tests/infrastructure/test_reads.py`
- Test: `tests/infrastructure/test_writes.py`

- [ ] **Step 1: Write the failing read test**

Add to `tests/infrastructure/test_reads.py`:

```python
def test_get_tags_empty(repo_impl):
    tags = repo_impl.get_tags()
    assert tags == []


def test_get_tags_lightweight(repo_path, repo_impl):
    raw = pygit2.Repository(str(repo_path))
    target = raw.head.target
    raw.references.create("refs/tags/v1.0.0", target)
    tags = repo_impl.get_tags()
    assert len(tags) == 1
    assert tags[0].name == "v1.0.0"
    assert tags[0].target_oid == str(target)
    assert tags[0].is_annotated is False
    assert tags[0].message is None


def test_get_tags_annotated(repo_path, repo_impl):
    raw = pygit2.Repository(str(repo_path))
    target = raw.head.target
    sig = pygit2.Signature("Tagger", "tagger@example.com")
    raw.create_tag("v2.0.0", target, pygit2.GIT_OBJECT_COMMIT, sig, "Release 2.0")
    tags = repo_impl.get_tags()
    annotated = [t for t in tags if t.name == "v2.0.0"]
    assert len(annotated) == 1
    assert annotated[0].is_annotated is True
    assert annotated[0].message == "Release 2.0"
    assert "Tagger" in annotated[0].tagger
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/infrastructure/test_reads.py::test_get_tags_empty -v`
Expected: FAIL — `AttributeError: 'Pygit2Repository' object has no attribute 'get_tags'`

- [ ] **Step 3: Implement get_tags**

Add to `git_gui/infrastructure/pygit2_repo.py` imports:

```python
from git_gui.domain.entities import (
    Branch, Commit, FileStatus, Hunk, Stash, Tag, WORKING_TREE_OID,
)
```

Add to the `Pygit2Repository` class in the reads section, after `get_stashes`:

```python
    def get_tags(self) -> list[Tag]:
        tags: list[Tag] = []
        for ref_name in self._repo.references:
            if not ref_name.startswith("refs/tags/"):
                continue
            ref = self._repo.references[ref_name]
            name = ref_name[len("refs/tags/"):]
            target = self._repo.get(ref.target)
            if isinstance(target, pygit2.Tag):
                # Annotated tag — peel to get the commit OID
                commit_oid = str(target.target.id) if hasattr(target.target, 'id') else str(target.target)
                # Peel through to the commit
                peeled = ref.peel(pygit2.Commit)
                commit_oid = str(peeled.id)
                ts = datetime.fromtimestamp(target.tagger.time, tz=timezone.utc) if target.tagger else None
                tagger_str = f"{target.tagger.name} <{target.tagger.email}>" if target.tagger else None
                tags.append(Tag(
                    name=name,
                    target_oid=commit_oid,
                    is_annotated=True,
                    message=target.message.strip() if target.message else None,
                    tagger=tagger_str,
                    timestamp=ts,
                ))
            else:
                # Lightweight tag — target is a commit directly
                tags.append(Tag(
                    name=name,
                    target_oid=str(ref.target),
                    is_annotated=False,
                    message=None,
                    tagger=None,
                    timestamp=None,
                ))
        return tags
```

- [ ] **Step 4: Run read tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_reads.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing write tests**

Add to `tests/infrastructure/test_writes.py`:

```python
def test_create_tag_lightweight(writable_repo):
    impl, path = writable_repo
    commits = impl.get_commits(limit=1)
    impl.create_tag("v1.0.0", commits[0].oid)
    raw = pygit2.Repository(str(path))
    assert "refs/tags/v1.0.0" in list(raw.references)


def test_create_tag_annotated(writable_repo):
    impl, path = writable_repo
    commits = impl.get_commits(limit=1)
    impl.create_tag("v2.0.0", commits[0].oid, message="Release 2.0")
    raw = pygit2.Repository(str(path))
    ref = raw.references["refs/tags/v2.0.0"]
    tag_obj = raw.get(ref.target)
    assert isinstance(tag_obj, pygit2.Tag)
    assert tag_obj.message == "Release 2.0"


def test_delete_tag(writable_repo):
    impl, path = writable_repo
    commits = impl.get_commits(limit=1)
    impl.create_tag("to-delete", commits[0].oid)
    impl.delete_tag("to-delete")
    raw = pygit2.Repository(str(path))
    assert "refs/tags/to-delete" not in list(raw.references)
```

- [ ] **Step 6: Run write tests to verify they fail**

Run: `uv run pytest tests/infrastructure/test_writes.py::test_create_tag_lightweight -v`
Expected: FAIL — `AttributeError: 'Pygit2Repository' object has no attribute 'create_tag'`

- [ ] **Step 7: Implement create_tag, delete_tag, push_tag**

Add to the `Pygit2Repository` class in the writes section:

```python
    def create_tag(self, name: str, oid: str, message: str | None = None) -> None:
        target = pygit2.Oid(hex=oid)
        if message:
            sig = self._get_signature()
            self._repo.create_tag(name, target, pygit2.GIT_OBJECT_COMMIT, sig, message)
        else:
            self._repo.references.create(f"refs/tags/{name}", target)

    def delete_tag(self, name: str) -> None:
        self._repo.references.delete(f"refs/tags/{name}")

    def push_tag(self, remote: str, name: str) -> None:
        self._run_git("push", remote, f"refs/tags/{name}")
```

- [ ] **Step 8: Run all tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 9: Commit**

```bash
git add git_gui/infrastructure/pygit2_repo.py tests/infrastructure/test_reads.py tests/infrastructure/test_writes.py
git commit -m "feat: implement tag read/write operations in pygit2 adapter"
```

---

### Task 3: Add application layer queries and commands

**Files:**
- Modify: `git_gui/application/queries.py`
- Modify: `git_gui/application/commands.py`
- Modify: `git_gui/presentation/bus.py`

- [ ] **Step 1: Add GetTags query**

In `git_gui/application/queries.py`, add `Tag` to the import:

```python
from git_gui.domain.entities import Branch, Commit, FileStatus, Hunk, Stash, Tag
```

Add the query class after `GetStashes`:

```python
class GetTags:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self) -> list[Tag]:
        return self._reader.get_tags()
```

- [ ] **Step 2: Add CreateTag, DeleteTag, PushTag commands**

In `git_gui/application/commands.py`, add after `DeleteBranch`:

```python
class CreateTag:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, name: str, oid: str, message: str | None = None) -> None:
        self._writer.create_tag(name, oid, message)


class DeleteTag:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, name: str) -> None:
        self._writer.delete_tag(name)


class PushTag:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, remote: str, name: str) -> None:
        self._writer.push_tag(remote, name)
```

- [ ] **Step 3: Wire into buses**

In `git_gui/presentation/bus.py`, update imports:

```python
from git_gui.application.queries import (
    GetCommitGraph, GetBranches, GetStashes, GetTags,
    GetCommitFiles, GetFileDiff, GetStagedDiff, GetWorkingTree,
    GetCommitDetail, IsDirty, GetHeadOid,
)
from git_gui.application.commands import (
    StageFiles, UnstageFiles, CreateCommit,
    Checkout, CheckoutCommit, CheckoutRemoteBranch, CreateBranch, DeleteBranch,
    CreateTag, DeleteTag, PushTag,
    Merge, Rebase, Push, Pull, Fetch,
    Stash, PopStash, ApplyStash, DropStash,
    StageHunk, UnstageHunk, FetchAllPrune,
)
```

Add `get_tags: GetTags` field to `QueryBus` (after `get_stashes`):

```python
    get_tags: GetTags
```

And in `QueryBus.from_reader()`:

```python
            get_tags=GetTags(reader),
```

Add fields to `CommandBus` (after `delete_branch`):

```python
    create_tag: CreateTag
    delete_tag: DeleteTag
    push_tag: PushTag
```

And in `CommandBus.from_writer()`:

```python
            create_tag=CreateTag(writer),
            delete_tag=DeleteTag(writer),
            push_tag=PushTag(writer),
```

- [ ] **Step 4: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add git_gui/application/queries.py git_gui/application/commands.py git_gui/presentation/bus.py
git commit -m "feat: add tag queries and commands to application layer and bus"
```

---

### Task 4: Tag badge colors in ref_badge_delegate

**Files:**
- Modify: `git_gui/presentation/widgets/ref_badge_delegate.py`
- Modify: `git_gui/presentation/widgets/commit_detail.py`

- [ ] **Step 1: Add tag color and update _badge_color**

In `git_gui/presentation/widgets/ref_badge_delegate.py`, add the tag color constant:

```python
COLOR_TAG = "#a371f7"     # purple — tag
```

Update `_badge_color()`:

```python
def _badge_color(name: str, head_branch: str | None = None) -> QColor:
    if name == "HEAD" or name.startswith("HEAD ->"):
        return QColor(COLOR_HEAD)
    if head_branch and name == head_branch:
        return QColor(COLOR_HEAD)
    if name.startswith("tag:"):
        return QColor(COLOR_TAG)
    if "/" in name:
        return QColor(COLOR_REMOTE)
    return QColor(COLOR_LOCAL)
```

- [ ] **Step 2: Add tag display name helper**

Add a helper function after `_badge_color`:

```python
def _badge_display_name(name: str) -> str:
    """Strip 'tag:' prefix for display."""
    if name.startswith("tag:"):
        return name[4:]
    return name
```

- [ ] **Step 3: Update RefBadgeDelegate.paint to use display name**

In `RefBadgeDelegate.paint()`, change the badge rendering loop:

```python
        for name in branch_names:
            display = _badge_display_name(name)
            badge_w = fm.horizontalAdvance(display) + BADGE_H_PAD * 2
            badge_rect = QRect(x, cy - badge_h // 2, badge_w, badge_h)

            painter.setBrush(QBrush(_badge_color(name)))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(badge_rect, BADGE_RADIUS, BADGE_RADIUS)

            painter.setPen(QColor("white"))
            painter.drawText(badge_rect, Qt.AlignCenter, display)

            x += badge_w + BADGE_GAP
```

- [ ] **Step 4: Update CommitInfoDelegate.paint to use display name**

In `git_gui/presentation/widgets/commit_info_delegate.py`, add the import:

```python
from git_gui.presentation.widgets.ref_badge_delegate import _badge_color, _badge_display_name
```

In the `paint` method, update the badge loop (around line 96-111):

```python
        for name in info.branch_names:
            display = _badge_display_name(name)
            badge_w = fm.horizontalAdvance(display) + BADGE_H_PAD * 2
            max_x = first_line_max_x if badge_line == 0 else cell_w
            if x > 0 and x + badge_w > max_x:
                badge_line += 1
                x = 0
            row_top = r2_top + badge_line * header_h
            cy = row_top + header_h // 2
            bx = rect.left() + CELL_PAD + x
            badge_rect = QRect(bx, cy - badge_h // 2, badge_w, badge_h)
            painter.setBrush(QBrush(_badge_color(name, info.head_branch)))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(badge_rect, BADGE_RADIUS, BADGE_RADIUS)
            painter.setPen(QColor("white"))
            painter.drawText(badge_rect, Qt.AlignCenter, display)
            x += badge_w + BADGE_GAP
```

Also update `_badge_line_count` to use display name for width calculation:

```python
def _badge_line_count(fm: QFontMetrics, branch_names: list[str],
                      first_line_width: int, full_width: int) -> int:
    if not branch_names:
        return 1
    lines = 1
    x = 0
    max_x = first_line_width
    for name in branch_names:
        display = _badge_display_name(name)
        badge_w = fm.horizontalAdvance(display) + BADGE_H_PAD * 2
        if x > 0 and x + badge_w > max_x:
            lines += 1
            x = 0
            max_x = full_width
        x += badge_w + BADGE_GAP
    return lines
```

- [ ] **Step 5: Update CommitDetailWidget.paintEvent to use display name**

In `git_gui/presentation/widgets/commit_detail.py`, add the import:

```python
from git_gui.presentation.widgets.ref_badge_delegate import (
    _badge_color, _badge_display_name, BADGE_RADIUS, BADGE_H_PAD, BADGE_V_PAD, BADGE_GAP,
)
```

Update the badge loop in `paintEvent` (around line 67-75):

```python
        for name in self._refs:
            display = _badge_display_name(name)
            badge_w = fm.horizontalAdvance(display) + BADGE_H_PAD * 2
            badge_rect = QRect(x, cy - badge_h // 2, badge_w, badge_h)
            painter.setBrush(QBrush(_badge_color(name)))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(badge_rect, BADGE_RADIUS, BADGE_RADIUS)
            painter.setPen(QColor("white"))
            painter.drawText(badge_rect, Qt.AlignCenter, display)
            x += badge_w + BADGE_GAP
```

- [ ] **Step 6: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add git_gui/presentation/widgets/ref_badge_delegate.py git_gui/presentation/widgets/commit_info_delegate.py git_gui/presentation/widgets/commit_detail.py
git commit -m "feat: add purple tag badge color and display name stripping"
```

---

### Task 5: Fetch tags in graph reload and add to refs dict

**Files:**
- Modify: `git_gui/presentation/widgets/graph.py`

- [ ] **Step 1: Update _LoadSignals**

Change the `_LoadSignals` class to include tags:

```python
class _LoadSignals(QObject):
    reload_done = Signal(list, list, list, bool, str)  # commits, branches, tags, is_dirty, head_oid
    append_done = Signal(list, list, list)              # more_commits, branches, tags
```

- [ ] **Step 2: Update reload worker to fetch tags**

In the `reload` method, update the worker:

```python
        def _worker():
            commits = queries.get_commit_graph.execute(limit=limit, extra_tips=extra_tips)
            branches = queries.get_branches.execute()
            tags = queries.get_tags.execute()
            dirty = queries.is_dirty.execute()
            head_oid = queries.get_head_oid.execute() or ""
            signals.reload_done.emit(commits, branches, tags, dirty, head_oid)
```

- [ ] **Step 3: Update _on_reload_done to accept tags and build refs**

Update the method signature and body:

```python
    def _on_reload_done(self, commits: list[Commit], branches: list[Branch],
                        tags, is_dirty: bool, head_oid: str) -> None:
        self._loading = False
        self._stash_btn.setVisible(is_dirty)
        if self._queries is None:
            return

        self._loaded_count = len(commits)
        self._has_more = len(commits) == self._reload_limit

        refs: dict[str, list[str]] = {}
        head_branch: str | None = None
        for b in branches:
            refs.setdefault(b.target_oid, []).append(b.name)
            if b.is_head and not b.is_remote:
                head_branch = b.name

        for t in tags:
            refs.setdefault(t.target_oid, []).append(f"tag:{t.name}")

        # Show HEAD badge only when detached (no local branch is HEAD)
        if head_oid and not head_branch:
            refs.setdefault(head_oid, []).insert(0, "HEAD")

        all_commits = list(commits)
        if is_dirty:
            synthetic = Commit(
                oid=WORKING_TREE_OID,
                message="Uncommitted Changes",
                author="",
                timestamp=datetime.now(),
                parents=[head_oid] if head_oid else [],
            )
            all_commits.insert(0, synthetic)

        self._model.reload(all_commits, refs, head_branch)
        self._update_column_widths()

        if self._pending_scroll_oid:
            found = any(
                self._model.data(self._model.index(r, 0), Qt.UserRole) == self._pending_scroll_oid
                for r in range(self._model.rowCount())
            )
            if found:
                self.scroll_to_oid(self._pending_scroll_oid, select=True)
                self._pending_scroll_oid = None
            elif self._has_more:
                oid = self._pending_scroll_oid
                tips = self._extra_tips
                new_limit = self._reload_limit * 2
                self._pending_scroll_oid = oid
                self._loading = False
                self.reload(extra_tips=tips, limit=new_limit)
            else:
                self._pending_scroll_oid = None
```

- [ ] **Step 4: Update _load_more worker and _on_append_done**

In `_load_more`:

```python
        def _worker():
            more = queries.get_commit_graph.execute(limit=PAGE_SIZE, skip=skip, extra_tips=self._extra_tips)
            branches = queries.get_branches.execute()
            tags = queries.get_tags.execute()
            signals.append_done.emit(more, branches, tags)
```

In `_on_append_done`:

```python
    def _on_append_done(self, more: list[Commit], branches: list[Branch], tags) -> None:
        self._loading = False
        if self._queries is None:
            return

        if not more:
            self._has_more = False
            return

        self._has_more = len(more) == PAGE_SIZE
        self._loaded_count += len(more)

        refs: dict[str, list[str]] = {}
        for b in branches:
            refs.setdefault(b.target_oid, []).append(b.name)
        for t in tags:
            refs.setdefault(t.target_oid, []).append(f"tag:{t.name}")

        self._model.append(more, refs)
```

- [ ] **Step 5: Add create_tag_requested signal and context menu item**

Add to `GraphWidget` signal declarations:

```python
    create_tag_requested = Signal(str)          # oid
```

In `_show_context_menu`, add "Create Tag..." after "Create Branch" (around line 362):

```python
        menu.addAction("Create Branch").triggered.connect(
            lambda: self.create_branch_requested.emit(oid))
        menu.addAction("Create Tag...").triggered.connect(
            lambda: self.create_tag_requested.emit(oid))
```

- [ ] **Step 6: Filter tag refs from branch context menu**

In `_show_context_menu`, update the branch name filtering to exclude tags:

```python
        # Filter out HEAD pseudo-ref and tag refs for branch operations
        real_branches = [n for n in branch_names if n != "HEAD" and not n.startswith("tag:")]
        local_branches = [n for n in real_branches if "/" not in n]
```

- [ ] **Step 7: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add git_gui/presentation/widgets/graph.py
git commit -m "feat: display tag badges on commit graph and add create tag menu"
```

---

### Task 6: Sidebar TAGS section

**Files:**
- Modify: `git_gui/presentation/widgets/sidebar.py`

- [ ] **Step 1: Update _LoadSignals to include tags**

```python
class _LoadSignals(QObject):
    done = Signal(list, list, list)  # branches, stashes, tags
```

- [ ] **Step 2: Add tag signals**

Add to `SidebarWidget` class signal declarations:

```python
    tag_clicked = Signal(str)               # target oid
    tag_delete_requested = Signal(str)       # tag name
    tag_push_requested = Signal(str)         # tag name
```

- [ ] **Step 3: Update reload worker**

In the `reload` method:

```python
        def _worker():
            branches = queries.get_branches.execute()
            stashes = queries.get_stashes.execute()
            tags = queries.get_tags.execute()
            signals.done.emit(branches, stashes, tags)
```

- [ ] **Step 4: Update _on_load_done to accept tags**

Change method signature and add TAGS section:

```python
    def _on_load_done(self, branches: list[Branch], stashes: list[Stash], tags) -> None:
        if self._queries is None:
            return

        self._model.clear()

        local = [b for b in branches if not b.is_remote]
        remote = [b for b in branches if b.is_remote]

        # Local branches — highlight HEAD
        local_header = QStandardItem("LOCAL BRANCHES")
        local_header.setEditable(False)
        local_header.setData("header", Qt.UserRole + 1)
        local_header.setSizeHint(QSize(0, _ROW_HEIGHT))
        for b in local:
            child = QStandardItem(b.name)
            child.setEditable(False)
            child.setData(b.name, Qt.UserRole)
            child.setData("branch", Qt.UserRole + 1)
            child.setData(b.target_oid, _TARGET_OID_ROLE)
            child.setSizeHint(QSize(0, _ROW_HEIGHT))
            if b.is_head:
                child.setData(True, _IS_HEAD_ROLE)
            local_header.appendRow(child)
        self._model.appendRow(local_header)

        # Remote branches
        self._add_section("REMOTE BRANCHES", [
            (b.name, b.name, "remote_branch", b.target_oid) for b in remote
        ])

        # Stashes
        self._add_section("STASHES", [
            (s.message, str(s.index), "stash", s.oid) for s in stashes
        ])

        # Tags
        self._add_section("TAGS", [
            (t.name, t.name, "tag", t.target_oid) for t in tags
        ])

        self._tree.expandAll()
```

- [ ] **Step 5: Update _on_click to handle tag clicks**

In `_on_click`:

```python
    def _on_click(self, index) -> None:
        kind = index.data(Qt.UserRole + 1)
        oid = index.data(_TARGET_OID_ROLE)
        if kind == "stash" and oid:
            self.stash_clicked.emit(oid)
        elif kind == "tag" and oid:
            self.tag_clicked.emit(oid)
        elif oid:
            self.branch_clicked.emit(oid)
```

- [ ] **Step 6: Update _show_context_menu to handle tags**

In `_show_context_menu`, update the kind check and add tag handling:

```python
    def _show_context_menu(self, pos) -> None:
        index = self._tree.indexAt(pos)
        kind = index.data(Qt.UserRole + 1)
        value = index.data(Qt.UserRole)
        if kind not in ("branch", "remote_branch", "stash", "tag"):
            return
        menu = QMenu(self)
        if kind == "branch":
            menu.addAction("Checkout").triggered.connect(
                lambda: (self._commands.checkout.execute(value),
                         self.branch_checkout_requested.emit(value)))
            menu.addAction("Merge into current").triggered.connect(
                lambda: self.branch_merge_requested.emit(value))
            menu.addAction("Rebase onto").triggered.connect(
                lambda: self.branch_rebase_requested.emit(value))
            menu.addSeparator()
            menu.addAction("Push").triggered.connect(
                lambda: self.branch_push_requested.emit(value))
            menu.addSeparator()
            menu.addAction("Delete").triggered.connect(
                lambda: self.branch_delete_requested.emit(value))
        elif kind == "remote_branch":
            remote = value.split("/")[0]
            menu.addAction("Fetch").triggered.connect(
                lambda: self.fetch_requested.emit(remote))
        elif kind == "stash":
            idx = int(value)
            menu.addAction("Pop").triggered.connect(
                lambda: self.stash_pop_requested.emit(idx))
            menu.addAction("Apply").triggered.connect(
                lambda: self.stash_apply_requested.emit(idx))
            menu.addSeparator()
            menu.addAction("Drop").triggered.connect(
                lambda: self.stash_drop_requested.emit(idx))
        elif kind == "tag":
            menu.addAction("Push").triggered.connect(
                lambda: self.tag_push_requested.emit(value))
            menu.addSeparator()
            menu.addAction("Delete").triggered.connect(
                lambda: self.tag_delete_requested.emit(value))
        menu.exec(self._tree.viewport().mapToGlobal(pos))
```

- [ ] **Step 7: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add git_gui/presentation/widgets/sidebar.py
git commit -m "feat: add TAGS section to sidebar with click and context menu"
```

---

### Task 7: CreateTagDialog and MainWindow wiring

**Files:**
- Create: `git_gui/presentation/widgets/create_tag_dialog.py`
- Modify: `git_gui/presentation/main_window.py`

- [ ] **Step 1: Create CreateTagDialog**

Create `git_gui/presentation/widgets/create_tag_dialog.py`:

```python
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout,
)


class CreateTagDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Tag")
        self.setMinimumWidth(350)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Tag name:"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. v1.0.0")
        layout.addWidget(self._name_edit)

        layout.addWidget(QLabel("Message (optional — leave empty for lightweight tag):"))
        self._message_edit = QLineEdit()
        self._message_edit.setPlaceholderText("e.g. Release 1.0.0")
        layout.addWidget(self._message_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Create")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._name_edit.setFocus()

    def _on_accept(self) -> None:
        if self._name_edit.text().strip():
            self.accept()

    def tag_name(self) -> str:
        return self._name_edit.text().strip()

    def tag_message(self) -> str | None:
        text = self._message_edit.text().strip()
        return text if text else None
```

- [ ] **Step 2: Wire tag signals in MainWindow**

In `git_gui/presentation/main_window.py`, add the import:

```python
from git_gui.presentation.widgets.create_tag_dialog import CreateTagDialog
```

Add signal connections in `__init__`, after the existing graph signal connections (around line 121):

```python
        self._graph.create_tag_requested.connect(self._on_create_tag)

        # Sidebar tag signals
        self._sidebar.tag_clicked.connect(self._graph.reload_with_extra_tip)
        self._sidebar.tag_delete_requested.connect(self._on_delete_tag)
        self._sidebar.tag_push_requested.connect(
            lambda name: self._run_remote_op(f"Push tag {name}", lambda: self._commands.push_tag.execute("origin", name)))
```

- [ ] **Step 3: Add tag handler methods**

Add to `MainWindow`, after `_on_create_branch`:

```python
    def _on_create_tag(self, oid: str) -> None:
        dialog = CreateTagDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        name = dialog.tag_name()
        message = dialog.tag_message()
        try:
            self._commands.create_tag.execute(name, oid, message)
            kind = "annotated" if message else "lightweight"
            self._log_panel.log(f"Created {kind} tag: {name}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Create tag — ERROR: {e}")
        self._reload()

    def _on_delete_tag(self, name: str) -> None:
        try:
            self._commands.delete_tag.execute(name)
            self._log_panel.log(f"Deleted tag: {name}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Delete tag {name} — ERROR: {e}")
        self._reload()
```

Add the `QDialog` import at the top:

```python
from PySide6.QtWidgets import (
    QDialog, QInputDialog, QMainWindow, QMessageBox, QSplitter, QStackedWidget,
    QVBoxLayout, QWidget,
)
```

- [ ] **Step 4: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/widgets/create_tag_dialog.py git_gui/presentation/main_window.py
git commit -m "feat: add CreateTagDialog and wire tag operations in MainWindow"
```

---

### Task 8: End-to-end verification

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: Manual verification**

Run: `uv run python main.py`

Verify:
1. Open a repo that has tags — tags appear as purple badges on commits in the graph
2. Tags appear as purple badges in commit detail panel
3. Sidebar shows TAGS section below STASHES
4. Click a tag in sidebar — graph scrolls to the tagged commit
5. Right-click a tag in sidebar — shows Push and Delete options
6. Right-click a commit in graph — shows "Create Tag..." option
7. Create Tag dialog appears with name and message fields
8. Create a lightweight tag (no message) — tag appears on the commit
9. Create an annotated tag (with message) — tag appears on the commit
10. Delete a tag from sidebar — tag disappears
