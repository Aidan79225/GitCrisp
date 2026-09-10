# Identity Prompt on Commit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the user clicks Commit without `user.name` / `user.email` configured, prompt inline to set them. Surface every commit error via the existing `commit_failed` signal so the log panel auto-expands instead of swallowing exceptions.

**Architecture:** Five pieces, port-driven per the project's Clean Architecture: domain ports (`get_identity`, `set_identity`), application wrappers (`GetIdentity`, `SetIdentity`), pygit2 implementation (config read + subprocess `git config` write), a new `IdentityDialog`, and wire-up in `WorkingTreeWidget._on_commit` that checks identity, prompts if missing, and wraps `create_commit.execute` in `try/except`.

**Tech Stack:** PySide6 (`QDialog`, `QLineEdit`, `QCheckBox`, `QFormLayout`, `QDialogButtonBox`), pygit2 (`repo.config`), subprocess (`git config`). Tests use `pytest-qt` (`qtbot`).

**Spec:** `docs/superpowers/specs/2026-05-09-identity-prompt-on-commit-design.md`

---

## File Structure

- **Create:** `git_gui/presentation/dialogs/identity_dialog.py` — modal `IdentityDialog`.
- **Create:** `tests/presentation/dialogs/test_identity_dialog.py` — dialog tests.
- **Modify:** `git_gui/domain/ports.py` — add `get_identity` (reader) and `set_identity` (writer).
- **Modify:** `git_gui/application/queries.py` — add `GetIdentity`.
- **Modify:** `git_gui/application/commands.py` — add `SetIdentity`.
- **Modify:** `git_gui/presentation/bus.py` — wire both into `QueryBus` and `CommandBus`.
- **Modify:** `git_gui/infrastructure/pygit2/repo_state_ops.py` — implement `get_identity` (config reads) and `set_identity` (subprocess `git config`).
- **Modify:** `git_gui/infrastructure/pygit2/commit_ops.py` — drop the `"Git GUI" <gitgui@localhost>` fallback in `_get_signature`.
- **Modify:** `git_gui/presentation/widgets/working_tree.py` — extend `_on_commit` to check identity, prompt on miss, wrap commit in `try/except`.
- **Modify:** `tests/infrastructure/test_reads.py` (or `test_writes.py`) — round-trip test for `get_identity` / `set_identity`.
- **Modify:** `tests/presentation/widgets/` — test asserting commit error surfaces via `commit_failed`.

---

## Task 1: Domain ports + application wrappers

Pure plumbing. No tests yet — these are abstract methods on the protocol. Tests exercise the infrastructure implementation in Task 2.

**Files:**
- Modify: `git_gui/domain/ports.py`
- Modify: `git_gui/application/queries.py`
- Modify: `git_gui/application/commands.py`
- Modify: `git_gui/presentation/bus.py`

- [ ] **Step 1: Add port methods**

In `git_gui/domain/ports.py`, find `IRepositoryReader` and add (next to other read methods):

```python
    def get_identity(self) -> tuple[str | None, str | None]: ...
    """Return (user.name, user.email) from repo config; either may be None if unset."""
```

Find `IRepositoryWriter` and add:

```python
    def set_identity(self, name: str, email: str, global_: bool) -> None: ...
    """Persist user.name and user.email via `git config [--global|--local]`."""
```

- [ ] **Step 2: Add `GetIdentity` query wrapper**

In `git_gui/application/queries.py`, add a new class near the other simple query wrappers (e.g., next to `GetTags`):

```python
class GetIdentity:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self) -> tuple[str | None, str | None]:
        return self._reader.get_identity()
```

- [ ] **Step 3: Add `SetIdentity` command wrapper**

In `git_gui/application/commands.py`, add a new class near other simple commands:

```python
class SetIdentity:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, name: str, email: str, global_: bool) -> None:
        self._writer.set_identity(name, email, global_)
```

- [ ] **Step 4: Wire into the buses**

In `git_gui/presentation/bus.py`:

Find the `QueryBus` dataclass and add a field:

```python
    get_identity: GetIdentity
```

Find the `CommandBus` dataclass and add:

```python
    set_identity: SetIdentity
```

Find the factory functions (or wherever each bus is constructed) and add the new args. Search for `get_tags=GetTags(reader)` for the query bus and `delete_remote_branch=DeleteRemoteBranch(writer)` for the command bus — add the new entries alongside:

```python
get_identity=GetIdentity(reader),
```

```python
set_identity=SetIdentity(writer),
```

Also add them to the imports at the top of `bus.py`:

```python
from git_gui.application.queries import (
    GetCommitGraph, GetBranches, GetStashes, GetTags, GetRemoteTags,
    GetCommitStats, GetIdentity,  # add this
    ...
)
```

```python
from git_gui.application.commands import (
    ...,
    SetIdentity,  # add this
)
```

- [ ] **Step 5: Run the full suite as a sanity check**

Run: `rtk uv run pytest tests/ -q`

Expected: all PASSED. The new ports are unused so far — no behavior changes, but the bus wiring should at least import cleanly.

If you get an `AbstractMethodError` from any test that constructs a `Pygit2Repository`, it means Task 2 needs to land before Task 1 can compile cleanly — drop down to Task 2 first and come back.

- [ ] **Step 6: Commit**

```bash
rtk git add git_gui/domain/ports.py git_gui/application/queries.py git_gui/application/commands.py git_gui/presentation/bus.py
rtk git commit -m "$(cat <<'EOF'
feat(domain,app): add get_identity / set_identity ports + bus wiring

Pure plumbing in preparation for the inline identity prompt on commit.
Reader port returns (name | None, email | None); writer takes
(name, email, global_) and persists via git config. Application
wrappers GetIdentity and SetIdentity follow the existing simple-
delegation pattern. Bus dataclasses gain matching fields.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: pygit2 implementation

Implement the new ports in `repo_state_ops.py`. TDD: write tests for both reads and writes first.

**Files:**
- Modify: `tests/infrastructure/test_reads.py`
- Modify: `git_gui/infrastructure/pygit2/repo_state_ops.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/infrastructure/test_reads.py`:

```python
def test_get_identity_returns_none_when_unset(repo_path):
    """A fresh repo with no user.name/user.email returns (None, None)."""
    import subprocess
    # Ensure repo-local config has no user.name/user.email.
    subprocess.run(
        ["git", "config", "--local", "--unset-all", "user.name"],
        cwd=str(repo_path), check=False,
    )
    subprocess.run(
        ["git", "config", "--local", "--unset-all", "user.email"],
        cwd=str(repo_path), check=False,
    )
    from git_gui.infrastructure.pygit2 import Pygit2Repository
    impl = Pygit2Repository(str(repo_path))
    name, email = impl.get_identity()
    # Note: a global config may set them. Test the "unset locally" path —
    # if global is set, both will be non-None; we just assert the call works.
    assert isinstance(name, (str, type(None)))
    assert isinstance(email, (str, type(None)))


def test_set_identity_local_then_get(repo_path):
    """set_identity(global_=False) writes user.name/user.email locally,
    and a subsequent get_identity returns them."""
    from git_gui.infrastructure.pygit2 import Pygit2Repository
    impl = Pygit2Repository(str(repo_path))
    impl.set_identity("Alice", "alice@example.com", global_=False)
    name, email = impl.get_identity()
    assert name == "Alice"
    assert email == "alice@example.com"


def test_set_identity_overwrites_existing(repo_path):
    """A second set_identity replaces the first values."""
    from git_gui.infrastructure.pygit2 import Pygit2Repository
    impl = Pygit2Repository(str(repo_path))
    impl.set_identity("Alice", "alice@example.com", global_=False)
    impl.set_identity("Bob", "bob@example.com", global_=False)
    name, email = impl.get_identity()
    assert name == "Bob"
    assert email == "bob@example.com"
```

- [ ] **Step 2: Run the tests and confirm FAIL**

Run: `rtk uv run pytest tests/infrastructure/test_reads.py -v -k "identity"`

Expected: 3 FAIL — `Pygit2Repository` has no `get_identity` / `set_identity` methods yet.

- [ ] **Step 3: Implement `get_identity`**

In `git_gui/infrastructure/pygit2/repo_state_ops.py`, add to the `RepoStateOps` mixin:

```python
    def get_identity(self) -> tuple[str | None, str | None]:
        """Return (user.name, user.email) from the merged git config.
        Either may be None if unset."""
        try:
            name = self._repo.config["user.name"]
        except KeyError:
            name = None
        try:
            email = self._repo.config["user.email"]
        except KeyError:
            email = None
        return name, email
```

- [ ] **Step 4: Implement `set_identity`**

Add to the same mixin, immediately after `get_identity`:

```python
    def set_identity(self, name: str, email: str, global_: bool) -> None:
        """Write user.name and user.email via subprocess `git config`.
        global_=True writes to ~/.gitconfig; False writes to this repo only."""
        import subprocess
        scope = "--global" if global_ else "--local"
        for key, value in (("user.name", name), ("user.email", email)):
            result = subprocess.run(
                ["git", "config", scope, key, value],
                cwd=self._repo.workdir or self._repo.path,
                env=self._git_env,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"git config {scope} {key} failed: "
                    f"{result.stderr.strip() or result.stdout.strip()}"
                )
```

- [ ] **Step 5: Run the tests and confirm PASS**

Run: `rtk uv run pytest tests/infrastructure/test_reads.py -v -k "identity"`

Expected: 3 PASSED.

- [ ] **Step 6: Run the full suite**

Run: `rtk uv run pytest tests/ -q`

Expected: all PASSED. (If Task 1 was deferred, do it now and re-run.)

- [ ] **Step 7: Commit**

```bash
rtk git add git_gui/infrastructure/pygit2/repo_state_ops.py tests/infrastructure/test_reads.py
rtk git commit -m "$(cat <<'EOF'
feat(infra): implement get_identity / set_identity in RepoStateOps

get_identity reads user.name and user.email from repo.config; either
returns None when missing (pygit2 raises KeyError). set_identity
shells out to `git config [--global|--local] user.name|user.email`,
matching the existing pattern for submodule mutations and using the
mixin's _git_env for repo-targeting.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: IdentityDialog

TDD. Three tests cover OK-button gating, value extraction, and pre-fill behavior.

**Files:**
- Create: `tests/presentation/dialogs/test_identity_dialog.py`
- Create: `git_gui/presentation/dialogs/identity_dialog.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/presentation/dialogs/test_identity_dialog.py`:

```python
"""Tests for IdentityDialog (inline prompt for missing git identity)."""
from __future__ import annotations

from PySide6.QtWidgets import QApplication, QDialogButtonBox

from git_gui.presentation.dialogs.identity_dialog import IdentityDialog


def _app():
    return QApplication.instance() or QApplication([])


def test_initial_empty_disables_ok(qtbot):
    _app()
    dlg = IdentityDialog(None, None)
    qtbot.addWidget(dlg)
    ok_btn = dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok)
    assert not ok_btn.isEnabled()


def test_filling_both_fields_enables_ok(qtbot):
    _app()
    dlg = IdentityDialog(None, None)
    qtbot.addWidget(dlg)
    ok_btn = dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok)
    dlg._name_edit.setText("Alice")
    dlg._email_edit.setText("alice@example.com")
    assert ok_btn.isEnabled()


def test_partial_initial_prefills_existing_field(qtbot):
    _app()
    dlg = IdentityDialog("Alice", None)
    qtbot.addWidget(dlg)
    assert dlg._name_edit.text() == "Alice"
    assert dlg._email_edit.text() == ""


def test_values_returns_trimmed_text_and_global_flag(qtbot):
    _app()
    dlg = IdentityDialog(None, None)
    qtbot.addWidget(dlg)
    dlg._name_edit.setText("  Alice  ")
    dlg._email_edit.setText("  alice@example.com  ")
    dlg._global_check.setChecked(True)
    name, email, global_ = dlg.values()
    assert name == "Alice"
    assert email == "alice@example.com"
    assert global_ is True


def test_global_checkbox_defaults_off(qtbot):
    _app()
    dlg = IdentityDialog(None, None)
    qtbot.addWidget(dlg)
    assert dlg._global_check.isChecked() is False
```

- [ ] **Step 2: Run the tests and confirm FAIL**

Run: `rtk uv run pytest tests/presentation/dialogs/test_identity_dialog.py -v`

Expected: 5 FAIL — `IdentityDialog` doesn't exist.

- [ ] **Step 3: Implement `IdentityDialog`**

Create `git_gui/presentation/dialogs/identity_dialog.py`:

```python
"""IdentityDialog — inline prompt for missing git user.name / user.email."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
    QLineEdit, QVBoxLayout, QWidget,
)


class IdentityDialog(QDialog):
    """Modal prompt for git user.name / user.email when missing.

    Pre-fills any value that's already set even if the other is missing.
    Ok is disabled until both fields are non-empty after stripping.
    """

    def __init__(
        self,
        initial_name: str | None,
        initial_email: str | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set Git Identity")
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Your git user.name and user.email aren't configured for this repo.\n"
            "Set them now to commit:"
        ))

        form = QFormLayout()
        self._name_edit = QLineEdit(initial_name or "")
        self._email_edit = QLineEdit(initial_email or "")
        form.addRow("Name:", self._name_edit)
        form.addRow("Email:", self._email_edit)
        layout.addLayout(form)

        self._global_check = QCheckBox("Save globally for all repos (--global)")
        layout.addWidget(self._global_check)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._ok_btn = buttons.button(QDialogButtonBox.Ok)

        self._name_edit.textChanged.connect(self._update_ok)
        self._email_edit.textChanged.connect(self._update_ok)
        self._update_ok()

    def _update_ok(self) -> None:
        self._ok_btn.setEnabled(
            bool(self._name_edit.text().strip())
            and bool(self._email_edit.text().strip())
        )

    def values(self) -> tuple[str, str, bool]:
        return (
            self._name_edit.text().strip(),
            self._email_edit.text().strip(),
            self._global_check.isChecked(),
        )
```

- [ ] **Step 4: Run the tests and confirm PASS**

Run: `rtk uv run pytest tests/presentation/dialogs/test_identity_dialog.py -v`

Expected: 5 PASSED.

- [ ] **Step 5: Run the full suite**

Run: `rtk uv run pytest tests/ -q`

Expected: all PASSED.

- [ ] **Step 6: Commit**

```bash
rtk git add git_gui/presentation/dialogs/identity_dialog.py tests/presentation/dialogs/test_identity_dialog.py
rtk git commit -m "$(cat <<'EOF'
feat(dialogs): IdentityDialog for inline git identity prompt

Modal QDialog with Name + Email QLineEdits, a "Save globally"
checkbox, and OK/Cancel. Ok stays disabled until both fields are
non-empty after stripping. values() returns the trimmed name + email
plus the global flag. Used by the next commit's working-tree
integration.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Working-tree integration + drop the bogus fallback

This is the user-facing change. Add the prompt path and the `try/except` around `create_commit`. Drop the `"Git GUI"` fallback now that the prompt covers the missing-identity case.

**Files:**
- Modify: `git_gui/presentation/widgets/working_tree.py`
- Modify: `git_gui/infrastructure/pygit2/commit_ops.py`
- Modify: `tests/presentation/widgets/test_working_tree.py` (or whichever test file owns the working-tree commit flow — check `Glob`)

- [ ] **Step 1: Drop the fallback in `commit_ops.py`**

In `git_gui/infrastructure/pygit2/commit_ops.py`, find:

```python
    def _get_signature(self) -> pygit2.Signature:
        try:
            return self._repo.default_signature
        except pygit2.GitError:
            return pygit2.Signature("Git GUI", "gitgui@localhost")
```

Replace with:

```python
    def _get_signature(self) -> pygit2.Signature:
        return self._repo.default_signature
```

If the user reaches `commit()` without configured identity, `default_signature` raises `GitError`; the calling code (in Task 4 Step 3) wraps it in `try/except` and surfaces via `commit_failed`.

- [ ] **Step 2: Find the working-tree test file**

Run: `rtk grep -rn "_on_commit\|commit_failed" tests/presentation/widgets/ 2>&1 | head -5`

Use the resulting file path. If no test file exists for the working-tree commit flow yet, create `tests/presentation/widgets/test_working_tree_commit.py`.

- [ ] **Step 3: Write the failing test**

Add (or create) the following test. Use a `MagicMock` query bus + command bus pattern to drive the widget without a real repo. Adjust the constructor call to match how other tests build `WorkingTreeWidget`:

```python
def test_on_commit_emits_failed_when_create_commit_raises(qtbot, monkeypatch):
    """When create_commit.execute raises, _on_commit must emit
    commit_failed with the error text and not call reload."""
    from unittest.mock import MagicMock
    from git_gui.presentation.widgets.working_tree import WorkingTreeWidget

    # Build the widget with mock buses. Adjust if construction differs.
    queries = MagicMock()
    commands = MagicMock()
    queries.get_identity.execute.return_value = ("Alice", "alice@example.com")
    commands.create_commit.execute.side_effect = RuntimeError("boom")

    w = WorkingTreeWidget(queries, commands)
    qtbot.addWidget(w)

    received: list[str] = []
    w.commit_failed.connect(lambda reason: received.append(reason))
    reload_called = []
    w.reload_requested.connect(lambda: reload_called.append(True))

    w._msg_edit.setPlainText("test commit message")
    # Simulate a clean repo state.
    w._current_state = "CLEAN"
    w._on_commit()

    assert received == ["Commit failed: boom"]
    assert reload_called == []
```

- [ ] **Step 4: Run the test and confirm FAIL**

Run: `rtk uv run pytest tests/presentation/widgets/test_working_tree_commit.py -v`

Expected: FAIL — either `get_identity` isn't on the bus yet, or the exception isn't caught (it propagates and pytest reports an error). Either is fine; both confirm new behavior is needed.

- [ ] **Step 5: Update `_on_commit` in `working_tree.py`**

Find the current `_on_commit` (around line 302). The existing block ends with:

```python
        if not msg:
            self.commit_failed.emit("Commit message is empty")
            return
        self._commands.create_commit.execute(msg)
        first_line = msg.split("\n")[0]
        self._msg_edit.clear()
        self.commit_completed.emit(first_line)
        self.reload_requested.emit()
        self.reload()
```

Replace with:

```python
        if not msg:
            self.commit_failed.emit("Commit message is empty")
            return

        # Identity check: if user.name or user.email is missing, prompt
        # the user inline rather than committing with a placeholder.
        name, email = self._queries.get_identity.execute()
        if not name or not email:
            from git_gui.presentation.dialogs.identity_dialog import IdentityDialog
            from PySide6.QtWidgets import QDialog
            dlg = IdentityDialog(name, email, parent=self)
            if dlg.exec() != QDialog.Accepted:
                return
            new_name, new_email, global_ = dlg.values()
            try:
                self._commands.set_identity.execute(new_name, new_email, global_)
            except Exception as e:
                self.commit_failed.emit(f"Failed to save identity: {e}")
                return

        try:
            self._commands.create_commit.execute(msg)
        except Exception as e:
            self.commit_failed.emit(f"Commit failed: {e}")
            return

        first_line = msg.split("\n")[0]
        self._msg_edit.clear()
        self.commit_completed.emit(first_line)
        self.reload_requested.emit()
        self.reload()
```

- [ ] **Step 6: Run the test and confirm PASS**

Run: `rtk uv run pytest tests/presentation/widgets/test_working_tree_commit.py -v`

Expected: PASSED.

- [ ] **Step 7: Run the full suite**

Run: `rtk uv run pytest tests/ -q`

Expected: all PASSED. The dropped fallback in `commit_ops.py` doesn't break any test because no existing test depends on the `"Git GUI" <gitgui@localhost>` placeholder.

- [ ] **Step 8: Commit**

```bash
rtk git add git_gui/infrastructure/pygit2/commit_ops.py git_gui/presentation/widgets/working_tree.py tests/presentation/widgets/test_working_tree_commit.py
rtk git commit -m "$(cat <<'EOF'
feat(commit): inline identity prompt + surface commit errors

Click Commit without user.name/user.email configured? An
IdentityDialog now pops, accepts Name + Email + a "save globally"
checkbox, and persists via SetIdentity before retrying the commit.
Cancel aborts silently.

create_commit.execute is now wrapped in try/except — any failure
(missing identity if somehow uncaught, locked index, hook reject,
etc.) emits commit_failed, which is already wired to expand the
log panel and show the reason. No more silent uncaught exceptions
out of the commit slot.

Drop the "Git GUI <gitgui@localhost>" fallback in
commit_ops._get_signature now that the prompt covers the missing-
identity case. If default_signature still raises somehow, the
new try/except in _on_commit surfaces the error.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Manual verification

**Files:** none modified.

- [ ] **Step 1: Launch the app**

Run: `rtk uv run python main.py`

- [ ] **Step 2: In a fresh repo with no identity, click Commit**

```bash
git init /tmp/test-identity-prompt
cd /tmp/test-identity-prompt
git config --local --unset-all user.name 2>/dev/null
git config --local --unset-all user.email 2>/dev/null
echo hi > a.txt
```

Open this repo in GitCrisp, stage `a.txt`, type a commit message, click Commit.

The IdentityDialog should appear with empty Name + Email fields and the global checkbox unchecked. Click Cancel — the working tree remains dirty, no commit happens, no error in the log panel.

- [ ] **Step 3: Re-click Commit, fill identity, accept**

The dialog appears again. Enter "Test User" + "test@example.com", leave the global checkbox off, click OK.

The commit proceeds. Run `git log -1` in the terminal — verify the author is "Test User <test@example.com>", NOT "Git GUI <gitgui@localhost>".

- [ ] **Step 4: Verify config was written locally**

Run: `git config --local --get user.name` → "Test User". `git config --get user.email` → "test@example.com".

- [ ] **Step 5: Verify partial pre-fill**

```bash
cd /tmp/test-identity-prompt
git config --local --unset user.name
```

Click Commit in GitCrisp again. The dialog appears with Name empty but Email pre-filled with "test@example.com". Type a name, click OK. Verify the commit goes through and `user.name` is now set.

- [ ] **Step 6: Verify error surfacing**

Configure a pre-commit hook that always fails:

```bash
cat > /tmp/test-identity-prompt/.git/hooks/pre-commit <<'EOF'
#!/bin/sh
echo "rejected by hook"
exit 1
EOF
chmod +x /tmp/test-identity-prompt/.git/hooks/pre-commit
```

Stage a change and click Commit. The log panel auto-expands and shows a "Commit failed: …" message — no silent failure.

- [ ] **Step 7: No commit needed**

Manual verification doesn't produce changes. If anything's off, surface before opening the PR.

---

## Self-Review

**Spec coverage:**
- IdentityDialog → Task 3. ✅
- Domain ports `get_identity` / `set_identity` → Task 1 Step 1. ✅
- Application wrappers `GetIdentity` / `SetIdentity` → Task 1 Steps 2-3. ✅
- Bus wiring → Task 1 Step 4. ✅
- pygit2 implementation reads + writes → Task 2 Steps 3-4. ✅
- Drop the bogus fallback → Task 4 Step 1. ✅
- `_on_commit` checks identity, prompts, wraps commit in try/except → Task 4 Step 5. ✅
- Tests for dialog (5), repo state ops (3), working-tree commit failure (1) → Task 3 Step 1, Task 2 Step 1, Task 4 Step 3. ✅

**Placeholder scan:** none — every step has full code or exact commands.

**Type/method consistency:**
- Port signatures match application wrappers and infrastructure: `get_identity() -> tuple[str | None, str | None]`, `set_identity(name: str, email: str, global_: bool) -> None`. ✅
- Bus field names match call sites: `self._queries.get_identity.execute()`, `self._commands.set_identity.execute(...)`. ✅
- `IdentityDialog.values() -> tuple[str, str, bool]` matches the destructuring in `_on_commit`. ✅
