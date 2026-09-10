# Identity prompt on commit

## Context

When the user clicks the Commit button without `user.name` and / or
`user.email` configured for the repo, the commit silently goes
through with the placeholder identity `"Git GUI" <gitgui@localhost>`
because `commit_ops.py:_get_signature` swallows pygit2's `GitError`
and falls back. Worse, if any other failure occurs in the commit
path, the exception bubbles out of the slot uncaught — the user
sees nothing.

The fix is two-pronged: detect missing identity before committing
and prompt the user to set it inline; surface every other commit
error via the existing `commit_failed` signal that's already wired
to the log panel.

## Decision (per Q&A)

When identity is missing: **prompt the user inline**. A modal
dialog accepts Name + Email and a checkbox for `--global` vs
`--local` (default `--local`). On accept, save via subprocess
`git config` and proceed with the commit. On cancel, abort.

## Architecture

Five pieces, following Clean Architecture's port pattern:

1. **Domain ports** — `IRepositoryReader.get_identity() -> tuple[str | None, str | None]`, `IRepositoryWriter.set_identity(name, email, global_) -> None`.
2. **Application** — `GetIdentity` query, `SetIdentity` command.
3. **Infrastructure** — pygit2 reads via `repo.config["user.name"|"user.email"]`; writes via `git config [--global|--local] user.name "…"` / `user.email "…"` subprocess.
4. **Presentation dialog** — `IdentityDialog` with two `QLineEdit`s + a `QCheckBox` + OK/Cancel.
5. **Wire-up** — `WorkingTreeWidget._on_commit` checks identity, prompts if missing, wraps `create_commit.execute(msg)` in `try/except` that emits `commit_failed`.

## What stays the same

- The `commit_failed` signal and its existing wiring to the log
  panel (which auto-expands on errors). We're just emitting it from
  more code paths.
- The empty-message check at the top of `_on_commit`.
- The state-aware branches (MERGING, REBASING, CHERRY_PICKING,
  REVERTING) above the message check.

## Drop the bogus fallback

`commit_ops.py:_get_signature` shrinks to:

```python
def _get_signature(self) -> pygit2.Signature:
    return self._repo.default_signature
```

If `default_signature` raises (no identity), the prompt path in
`WorkingTreeWidget._on_commit` will have caught it before calling
`create_commit`. If it somehow gets here (e.g., user unsets
identity after the prompt check), the exception now propagates and
surfaces via the new `try/except` around `create_commit.execute`.

## IdentityDialog

`git_gui/presentation/dialogs/identity_dialog.py`:

```python
class IdentityDialog(QDialog):
    """Modal prompt for git user.name / user.email when missing."""

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

## Working-tree commit flow

```python
def _on_commit(self) -> None:
    state = getattr(self, "_current_state", "CLEAN")
    msg = self._msg_edit.toPlainText().strip()
    if state == "MERGING":
        self.merge_continue_requested.emit(msg); return
    if state == "REBASING":
        self.rebase_continue_requested.emit(msg); return
    if state == "CHERRY_PICKING":
        self.cherry_pick_continue_requested.emit(); return
    if state == "REVERTING":
        self.revert_continue_requested.emit(); return
    if not msg:
        self.commit_failed.emit("Commit message is empty"); return

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

## Files

- **Create:** `git_gui/presentation/dialogs/identity_dialog.py`
- **Create:** `tests/presentation/dialogs/test_identity_dialog.py`
- **Modify:** `git_gui/domain/ports.py`
- **Modify:** `git_gui/application/queries.py`
- **Modify:** `git_gui/application/commands.py`
- **Modify:** `git_gui/presentation/bus.py`
- **Modify:** `git_gui/infrastructure/pygit2/repo_state_ops.py`
- **Modify:** `git_gui/infrastructure/pygit2/commit_ops.py`
- **Modify:** `git_gui/presentation/widgets/working_tree.py`
- **Modify:** `tests/presentation/widgets/` — add a working-tree test asserting commit error surfaces via `commit_failed`.

## Tests

- **`test_identity_dialog.py`** — OK button disabled when either field empty; `values()` returns trimmed text + checkbox state.
- **Working-tree test** — when `create_commit.execute` raises, `_on_commit` emits `commit_failed` with the error text; reload is NOT triggered.
- **Repo state ops** — `get_identity` returns `(None, None)` on a fresh repo; returns the configured pair after `set_identity(name, email, global_=False)`.

## Verification

**Automated:**
```
uv run pytest tests/presentation/dialogs/test_identity_dialog.py -v
uv run pytest tests/infrastructure/ -v
uv run pytest tests/presentation/widgets/ -v
uv run pytest tests/ -q
```

**Manual:**
1. In a repo with `user.name`/`user.email` unset, stage a change, click Commit. Identity dialog appears.
2. Enter name + email, leave checkbox off, click OK. Commit goes through with that identity. Verify `git log -1` shows the new author.
3. Repeat in a repo where one of the two is set — dialog pre-fills the existing field.
4. Cancel the dialog — commit aborts silently; staged changes remain staged.
5. Configure identity, then deliberately break something (e.g., make the repo HEAD point at a missing object). Commit. The log panel auto-expands and shows a clear error.
