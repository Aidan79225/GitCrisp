# Git Menu: Remote & Submodule Management Dialogs

**Date:** 2026-04-08
**Status:** Approved

## Overview

Add a new `Git` menu to the main window menubar with two items: `Remotes...` and `Submodules...`. Each opens a dedicated dialog for managing the corresponding repository configuration.

Scope:
- **Remotes:** Basic CRUD — list, add, rename, change URL, remove.
- **Submodules:** Basic CRUD (list, add, change URL, remove) plus an "Open" action that switches the current main window to the submodule repo (one-way switch, same flow as opening any other repo).

## Architecture

Follows the existing clean-architecture layout (`domain` → `application` → `infrastructure` → `presentation`) and mirrors the existing `View → Appearance...` / `ThemeDialog` pattern.

### New files

- `git_gui/presentation/menus/git_menu.py` — installs the `Git` menu (mirrors `appearance.py`).
- `git_gui/presentation/dialogs/remote_dialog.py` — `RemoteDialog(QDialog)`.
- `git_gui/presentation/dialogs/submodule_dialog.py` — `SubmoduleDialog(QDialog)`.
- `tests/presentation/dialogs/test_remote_dialog.py`
- `tests/presentation/dialogs/test_submodule_dialog.py`
- `tests/infrastructure/test_pygit2_repo_remotes.py`
- `tests/infrastructure/test_pygit2_repo_submodules.py`

### Modified files

- `git_gui/domain/entities.py` — add dataclasses:
  - `Remote(name: str, fetch_url: str, push_url: str)`
  - `Submodule(path: str, url: str, head_sha: str | None)`
- `git_gui/domain/ports.py` — extend the repo port:
  - Remotes: `list_remotes()`, `add_remote(name, url)`, `remove_remote(name)`, `rename_remote(old, new)`, `set_remote_url(name, url)`
  - Submodules: `list_submodules()`, `add_submodule(path, url)`, `remove_submodule(path)`, `set_submodule_url(path, url)`
- `git_gui/infrastructure/pygit2_repo.py` — implement the new methods. Remotes use pygit2 directly. Submodule listing uses pygit2; submodule add/remove/url-change shell out to the `git` CLI via `subprocess` (see Caveats).
- `git_gui/presentation/main_window.py` — call `install_git_menu(self)` next to `install_appearance_menu(self)`. Wire the dialog's `submoduleOpenRequested(abs_path)` signal to the existing "open repo" code path.

## Remote Dialog

### Layout

```
┌─ Remotes ──────────────────────────────┐
│  ┌─────────────────────────────────┐   │
│  │ Name    │ Fetch URL │ Push URL  │   │
│  │ origin  │ git@...   │ git@...   │   │
│  │ upstream│ https://..│ (same)    │   │
│  └─────────────────────────────────┘   │
│  [ Add... ] [ Edit... ] [ Remove ]    │
│                           [ Close ]    │
└────────────────────────────────────────┘
```

### Operations

- **Add** → modal with `Name` + `URL` fields. Validates name is non-empty and unique; URL non-empty.
- **Edit** → modal pre-filled with `Name` (editable → triggers rename) and `URL` (editable → triggers set-url). Applies whichever changed.
- **Remove** → confirmation dialog ("Remove remote 'origin'?"), then removes.
- **Close** → dismisses.

### Refresh

After every mutation, re-query `list_remotes()` and rebuild the table. Synchronous, no threading.

## Submodule Dialog

### Layout

```
┌─ Submodules ───────────────────────────────────┐
│  ┌──────────────────────────────────────────┐  │
│  │ Path         │ URL          │ HEAD       │  │
│  │ libs/foo     │ git@.../foo  │ a1b2c3d    │  │
│  │ vendor/bar   │ https://...  │ 9f8e7d6    │  │
│  └──────────────────────────────────────────┘  │
│  [ Add... ] [ Edit URL... ] [ Remove ] [Open] │
│                                   [ Close ]   │
└────────────────────────────────────────────────┘
```

### Operations

- **Add** → modal with `Path` (relative) + `URL`. Runs `git submodule add <url> <path>`.
- **Edit URL** → modal with new URL. Updates `.gitmodules` and runs `git submodule sync <path>`.
- **Remove** → confirmation. Runs the standard removal sequence:
  1. `git submodule deinit -f <path>`
  2. `git rm -f <path>`
  3. `rm -rf .git/modules/<path>`
- **Open** → emits `submoduleOpenRequested(abs_path: str)` and closes the dialog. `main_window` reuses its existing open-repo path to switch the current window to the submodule repo. **One-way switch** — no back navigation.
- **Close** → dismisses.

### Refresh

Same as Remote dialog: re-query after every mutation.

## pygit2 Caveats: Why Shell Out for Submodules

pygit2 supports listing submodules and reading their metadata, but `add` / `remove` / URL changes are not well covered. Shelling out to the `git` CLI via `subprocess` is the pragmatic and reliable choice.

- **Trade-off accepted:** Adds a runtime dependency on `git` being on `PATH`.
- **Failure mode:** If `git` is not found, mutation operations show a dedicated error: "`git` executable not found on PATH". Listing and Open continue to work because they go through pygit2 / filesystem paths.
- A typed `SubmoduleCommandError(stderr)` is raised by the subprocess wrapper so the dialog can surface a clean message.

## Menu Installation

`git_menu.py` mirrors `appearance.py`:

```python
def install_git_menu(window: QMainWindow) -> None:
    bar = window.menuBar()
    git_menu = bar.addMenu("&Git")
    remote_action = QAction("&Remotes...", window)
    remote_action.triggered.connect(lambda: RemoteDialog(window._repo, window).exec())
    submodule_action = QAction("&Submodules...", window)
    submodule_action.triggered.connect(lambda: _open_submodule_dialog(window))
    git_menu.addAction(remote_action)
    git_menu.addAction(submodule_action)
    window._git_remote_action = remote_action
    window._git_submodule_action = submodule_action
```

The submodule helper constructs the dialog and connects `submoduleOpenRequested` to the main window's open-repo path. `install_git_menu(self)` is called from `MainWindow.__init__` alongside `install_appearance_menu(self)`.

## Error Handling

Consistent pattern across both dialogs:

- All port calls wrapped in `try/except Exception as e:` at the dialog layer.
- On error: `QMessageBox.warning(self, "<Operation> failed", str(e))`. Dialog stays open. Table is re-queried so the UI reflects actual state.
- The submodule subprocess wrapper raises `SubmoduleCommandError(stderr)`; the dialog presents `stderr` directly.
- Missing `git` binary → dedicated message: "`git` executable not found on PATH".

## Testing

- **Dialog unit tests** (`pytest-qt`): mock the repo port; verify the table populates correctly, Add/Edit/Remove invoke the right port methods with the right arguments, the error path shows a `QMessageBox`, and `submoduleOpenRequested` fires with the correct absolute path on Open.
- **Infrastructure integration tests:**
  - Remotes: build a real temp repo with pygit2 and exercise remote CRUD directly.
  - Submodules: create a real temp parent repo and a second local repo to act as the submodule source; exercise add / set-url / remove via the subprocess wrapper. **No subprocess mocking** — real `git` calls.
- **Menu smoke test:** verify `install_git_menu` adds the two actions to a `QMainWindow`.

All Python operations run via `uv run` per `CLAUDE.md`.

## Out of Scope (YAGNI)

- Remote fetch / prune buttons.
- Submodule init / update / sync buttons.
- Drag-and-drop, multi-select bulk ops, keyboard shortcuts.
- Background threading.
- Back navigation from a submodule to the parent repo.
- Surfacing remote/submodule entry points outside the `Git` menu (sidebar context menu, toolbar).
