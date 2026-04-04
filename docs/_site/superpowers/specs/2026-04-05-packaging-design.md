# Packaging & CI/CD Release Design

## Goal

Package GitStack as a standalone executable for Windows, macOS, and Linux using PyInstaller, with GitHub Actions CI/CD to automatically build and publish releases.

## PyInstaller Configuration

- **Mode:** `--onedir` (faster startup, fewer issues with PySide6 and pygit2 native libs than `--onefile`)
- **Console:** `--windowed` (no console window on Windows/macOS)
- **Native dependencies:** `--collect-all pygit2` to ensure libgit2 shared libraries are bundled
- **Assets:** `arts/` directory (SVG icons) included as data files
- **Output name:** `GitStack`
- **Config file:** `GitStack.spec` at project root

### Spec file details

- `datas`: include `arts/` folder mapped to `arts/` in the bundle
- `hiddenimports`: `pygit2` submodules if auto-detection misses them
- `Analysis` pathex: project root
- `EXE` name: `GitStack`
- Platform-specific: `console=False` for Windows/macOS, `console=False` for Linux (GUI app)

### arts/ path resolution

Currently `graph.py` resolves arts path as:
```python
_ARTS = Path(__file__).resolve().parent.parent.parent.parent / "arts"
```

This breaks when running from a PyInstaller bundle because `__file__` points inside the frozen app. Need a helper that checks `sys._MEIPASS` (PyInstaller's temp extraction dir) first:

```python
import sys
from pathlib import Path

def get_resource_path(relative: str) -> Path:
    if getattr(sys, '_MEIPASS', None):
        return Path(sys._MEIPASS) / relative
    return Path(__file__).resolve().parent.parent.parent.parent / relative
```

All references to `arts/` must use this helper. Currently referenced in:
- `git_gui/presentation/widgets/graph.py` (`_ARTS`)

## GitHub Actions CI/CD

### Workflow: `.github/workflows/release.yml`

**Trigger:** push tag matching `v*` (e.g., `v0.1.0`)

**Jobs:**

#### 1. `build` (matrix strategy)

Runs on three platforms in parallel:

| Platform | Runner | Archive format |
|----------|--------|---------------|
| Windows | `windows-latest` | `.zip` |
| macOS | `macos-latest` | `.tar.gz` |
| Linux | `ubuntu-latest` | `.tar.gz` |

Steps per platform:
1. Checkout code
2. Set up Python 3.13
3. Install uv
4. `uv sync` (install dependencies)
5. `uv run pytest -v` (run tests, fail fast)
6. `uv pip install pyinstaller`
7. `uv run pyinstaller GitStack.spec`
8. Archive `dist/GitStack/` → `GitStack-{os}-{tag}.{ext}`
9. Upload archive as workflow artifact

#### 2. `release` (depends on `build`)

Runs after all three build jobs succeed:
1. Download all three artifacts
2. Create GitHub Release from the tag
3. Upload the three archives as release assets

### Release naming

- `GitStack-windows-v0.1.0.zip`
- `GitStack-macos-v0.1.0.tar.gz`
- `GitStack-linux-v0.1.0.tar.gz`

## Files to create/modify

- **Create:** `GitStack.spec` — PyInstaller spec file
- **Create:** `.github/workflows/release.yml` — CI/CD workflow
- **Create:** `git_gui/resources.py` — resource path helper (`get_resource_path`)
- **Modify:** `git_gui/presentation/widgets/graph.py` — use `get_resource_path("arts")` instead of `Path(__file__)` resolution
- **Modify:** `pyproject.toml` — add `pyinstaller` to dev dependencies
