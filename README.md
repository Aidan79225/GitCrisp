# GitCrisp

A clean, focused desktop Git client built with Python and PySide6 (Qt) for everyday Git workflows. Visual commit graph, per-hunk staging, multi-repository management, and full management dialogs for branches, remotes, submodules, tags, and themes.

## Screenshot

![GitCrisp](docs/screenshot/basic-view.png)

## Features

### Commit Graph & History
- Lane-based visual graph with topological + time sort
- Lazy pagination — automatically expands the loaded range to reach distant branches
- **Inline search** (Ctrl+F) — search commit messages, authors, hashes, and dates across the full history
- Click any commit to view its file list and unified diff
- **Collapsing commit header** — commit info + message smoothly shrink as you scroll the diff, maximizing space for hunks (re-expands on scroll-up)
- Click a branch in the sidebar to scroll the graph to its HEAD

### Working Tree & Staging
- File-level stage / unstage with checkbox toggles
- **Per-hunk staging** — stage or unstage individual diff hunks within a file
- Inline diff viewer with line numbers, monospace font, and added/removed highlighting
- **Syntax highlighting** in diff hunks via Pygments — supports hundreds of languages
- **Word-level intra-line diff** highlights the changed words within `-`/`+` line pairs
- **Lazy diff loading** — skeleton placeholders that realize on scroll for smooth handling of large commits
- Discard a single hunk or an entire file from the diff view
- Add files to `.gitignore` from the context menu
- Commit message editor with immediate feedback

### Branch Management
- Local + remote branches in a collapsible sidebar tree (HEAD highlighted)
- Graph context menu — create, delete, checkout, merge, rebase
- **Merge options dialog** — choose strategy (no-ff / ff-only / allow-ff), edit commit message, see merge analysis ("can fast-forward" / "requires merge commit")
- **Interactive rebase** — commit list editor with action dropdowns (pick / squash / fixup / drop) and drag-and-drop row reordering
- **`Git → Branches...`** dialog: list local branches with their upstream and last commit; checkout, create, rename, delete, and set/unset upstream
- **Checkout-conflict prompt** — when checking out a remote branch whose same-named local branch already exists, offer to hard-reset the local to the remote HEAD

### Commit Operations
- **Cherry-pick** — right-click a commit in the graph → "Cherry-pick commit …"
- **Revert** — right-click a commit → "Revert commit …" (creates an inverse commit on HEAD)
- **Reset** — right-click an ancestor of HEAD → "Reset <branch> to <sha> ▸" with soft / mixed / hard modes; hard shows a dirty-file preview before confirming
- Cherry-pick / revert conflicts are surfaced by the existing conflict banner with Abort and Continue buttons

### Conflict Resolution
- **Merge / rebase conflict banner** — visible in both the working tree and commit detail panels with Abort and Continue buttons
- Conflict files marked with red "C" badge and sorted to top of the file list
- Conflict hunks shown per conflict block (`<<<<<<<` to `>>>>>>>`) with ours/theirs coloring
- Graph shows dual-parent synthetic row during merge conflicts ("Merge in progress")
- Resolved files diff against HEAD when conflict markers are removed

### Tags
- Create lightweight or annotated tags from any commit
- Delete tags
- Push individual tags to a remote
- Tag refs shown in the sidebar and on the graph

### Stash
- One-click stash from the toolbar with confirmation
- View stash contents (file list + diff) by clicking a stash in the sidebar
- Pop, apply, or drop stashes via context menu

### Remote Operations
- Push, pull, fetch, and fetch-all-prune from the toolbar
- Fetch from a specific remote via sidebar context menu
- **Force push dialog** — when a push is rejected (non-fast-forward), offers to force push with `--force-with-lease`
- **`Git → Remotes...`** dialog: list, add, edit (rename / change URL), and remove remotes
- All remote operations run in background threads with status bar indicator

### Submodule Support
- **`Git → Submodules...`** dialog: list, add, edit URL, remove submodules; click "Open" to switch the current window to the submodule repo
- **Click-to-open in diffs** — file and hunk headers for submodule changes are clickable; click to jump into the submodule repo
- Clone with `--recurse-submodules` automatically

### Multi-Repository
- Switch between repositories with persistent open and recent lists
- **Two-line repo entries** — directory name + home-relative path for disambiguation
- **Drag-and-drop reordering** of open repositories in the sidebar
- Submodules opened from a parent appear grouped below the parent
- Open repositories from disk or clone from URL
- Persistent state in `~/.gitcrisp/repos.json`

### Theming
- Light and dark themes selectable from **`View → Appearance...`**
- Custom typography scale (snaps to 10% steps) for the entire UI
- Live preview, no restart needed

### Insights
- Per-author commit stats over a configurable date range
- Useful for retrospectives and contribution overviews

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| F5 | Reload |
| Ctrl+F | Search commits (message, author, hash, date) |
| Ctrl+W | Close current repo and switch to previous |
| Ctrl+1..9 | Switch to Nth open repo |

### Diagnostics
- Rotating file logger at `~/.gitcrisp/logs/gitcrisp.log` (1 MB × 4 files)
- Uncaught exceptions logged with full tracebacks (main thread + background workers)

## Architecture

GitCrisp follows **Clean Architecture** with strict layer separation:

```
git_gui/
├── domain/           # Entities (Commit, Branch, Tag, Stash, Remote, Submodule,
│                     #            LocalBranchInfo, FileStatus, Hunk, ...)
│                     # Protocols (IRepositoryReader, IRepositoryWriter, IRepoStore)
│
├── application/      # Use cases — one class per operation
│   ├── commands.py   # Write: stage, commit, checkout, push, stash, create_tag,
│   │                 #         add_remote, add_submodule, set_branch_upstream, ...
│   └── queries.py    # Read: get_commits, get_branches, get_file_diff,
│                     #        list_remotes, list_submodules,
│                     #        list_local_branches_with_upstream, ...
│
├── infrastructure/   # Adapters
│   ├── pygit2/           # Pygit2Repository — composite of ten mixin modules
│   │   ├── repository.py     # Composite class (Pygit2Repository)
│   │   ├── branch_ops.py     # Branch read/write
│   │   ├── commit_ops.py     # Commit read/write + cherry-pick/revert/reset
│   │   ├── diff_ops.py       # Diff / hunk / file status
│   │   ├── stage_ops.py      # Stage / unstage / hunk stage / discard
│   │   ├── tag_ops.py        # Tag read/write
│   │   ├── stash_ops.py      # Stash list/create/pop/apply/drop
│   │   ├── merge_rebase_ops.py  # Merge / rebase / interactive / abort / continue
│   │   ├── remote_ops.py     # Remote list/add/remove/rename + push/pull/fetch
│   │   ├── submodule_ops.py  # Submodule operations + gitdir helpers
│   │   ├── repo_state_ops.py # HEAD / state / conflicts / _git_env
│   │   └── _helpers.py       # Pure functions (status map, entity conversion, synthesis)
│   ├── commit_ops_cli.py  # `git cherry-pick` / `git revert` subprocess wrapper
│   ├── submodule_cli.py   # `git submodule` subprocess wrapper
│   ├── repo_store.py      # JSON-based repository persistence
│   └── git_clone.py       # Clone helper (recursive)
│
└── presentation/     # Qt UI layer
    ├── main_window.py        # Signal orchestration between widgets
    ├── bus.py                # Command / Query bus (DI containers)
    ├── menus/                # Menubar installers (View, Git)
    ├── dialogs/              # Branches, Remotes, Submodules, Theme,
    │                         #   Insight, Clone, CreateTag, Merge,
    │                         #   InteractiveRebase
    ├── theme/                # Theme manager + tokens
    ├── models/               # QAbstractTableModel / QAbstractListModel
    └── widgets/              # Graph, Sidebar, Diff, WorkingTree, LogPanel, ...
```

**Key design decisions:**

- **Protocol-based dependency injection** — domain defines interfaces, infrastructure implements them, presentation consumes them through buses.
- **Signal-bridge pattern** — no widget-to-widget references. `MainWindow` wires all cross-widget communication via Qt signals.
- **Background threading** — remote operations and data loading run in worker threads; results are marshalled to the main thread via `QObject` signal bridges.
- **pygit2 first, subprocess where needed** — branch / remote / tag / stash operations use pygit2 directly; submodule mutations shell out to `git` because pygit2 lacks reliable submodule add / remove support.

## Requirements

- Python >= 3.13
- PySide6 >= 6.11.0
- pygit2 >= 1.19.2

## Getting Started

```bash
# Clone the repository
git clone https://github.com/Aidan79225/GitCrisp.git
cd GitCrisp

# Install dependencies (using uv)
uv sync

# Run the application
uv run python main.py
```

## Running Tests

```bash
uv run pytest -v
```

## License

MIT
