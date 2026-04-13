# Repo Path Validation — Design Spec

## Problem

The app crashes (unhandled `pygit2.GitError`) when opening a path that is a valid directory but not a git repository. This happens when:

1. A previously-opened repo stored in `~/.gitcrisp/repos.json` has its `.git` deleted or becomes invalid
2. A user selects a non-git directory via the file picker

The crash occurs at `main.py:63` where `Pygit2Repository(repo_path)` is called without validation.

## Solution

Validate that a path is a git repository **at every entry point** before it reaches `Pygit2Repository`. On failure, show an error message and re-open the directory picker.

### Validation helper

Add a helper function in `main.py`:

```python
def _is_git_repo(path: str) -> bool:
    return pygit2.discover_repository(path) is not None
```

`pygit2.discover_repository` walks up the directory tree looking for `.git`. Returns `None` if not found. Handles standard repos, bare repos, and subdirectories.

## Changes

### 1. `main.py:_find_valid_repo()`

Add `_is_git_repo()` check alongside existing `is_dir()`:

```python
if active and Path(active).is_dir() and _is_git_repo(active):
    return active

for path in list(repo_store.get_open_repos()):
    if Path(path).is_dir() and _is_git_repo(path):
        repo_store.set_active(path)
        return path
    repo_store.close_repo(path)
```

Invalid paths are pruned from the store (existing behavior, now also covers non-git directories).

### 2. `main.py:_pick_repo()`

Loop until user picks a valid git repo or cancels:

```python
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
```

### 3. `git_gui/presentation/widgets/repo_list.py:_on_add_clicked()`

Same validation-and-retry pattern before emitting `repo_open_requested`:

```python
def _on_add_clicked(self) -> None:
    while True:
        dialog = QFileDialog()
        dialog.setWindowTitle("Open Repository")
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setOption(QFileDialog.ShowDirsOnly, True)
        if dialog.exec() != QFileDialog.Accepted:
            return
        dirs = dialog.selectedFiles()
        if not dirs:
            return
        path = dirs[0]
        if _is_git_repo(path):
            self.repo_open_requested.emit(path)
            return
        QMessageBox.warning(
            self,
            "Not a Git Repository",
            "The selected folder is not a Git repository.\n"
            "Please choose a folder that contains a Git repository.",
        )
```

`repo_list.py` will need to import `pygit2` (or import the helper). Since `_is_git_repo` is a one-liner, it can be duplicated or extracted to a small utility.

### 4. No changes needed

- **`main.py:main()` line 63** — After the above fixes, `repo_path` is guaranteed valid.
- **`main_window.py:_on_repo_open()`** — Receives already-validated paths from repo_list.
- **`main_window.py:_switch_repo()`** — Already has try/except error handling.

## Error message

Consistent across all entry points:

> **Not a Git Repository**
>
> The selected folder is not a Git repository.
> Please choose a folder that contains a Git repository.

## Testing

- Unit test: `_is_git_repo` returns `True` for a valid repo, `False` for a plain directory
- Unit test: `_find_valid_repo` prunes non-git directories from the store
- Manual test: select a non-git folder in the file picker, verify error + retry
- Manual test: corrupt `~/.gitcrisp/repos.json` with a non-git path, verify graceful recovery
