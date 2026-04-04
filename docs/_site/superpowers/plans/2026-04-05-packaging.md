# Packaging & CI/CD Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package GitStack as a standalone executable for Windows/macOS/Linux using PyInstaller, with GitHub Actions CI/CD to build and publish releases on tag push.

**Architecture:** Create a resource path helper for PyInstaller compatibility, a `.spec` file for build configuration, and a GitHub Actions workflow that builds on three platforms and creates a GitHub Release with artifacts.

**Tech Stack:** PyInstaller, GitHub Actions, uv

---

### Task 1: Resource path helper

**Files:**
- Create: `git_gui/resources.py`
- Test: `tests/test_resources.py`
- Modify: `git_gui/presentation/widgets/graph.py:66`

- [ ] **Step 1: Write test for resource path helper**

Create `tests/test_resources.py`:

```python
import sys
from pathlib import Path
from git_gui.resources import get_resource_path


def test_get_resource_path_normal():
    """In normal (non-frozen) mode, resolves relative to project root."""
    result = get_resource_path("arts")
    # Should point to the arts/ directory at project root
    assert result.name == "arts"
    assert result.parent == Path(__file__).resolve().parent.parent


def test_get_resource_path_frozen(monkeypatch):
    """In PyInstaller frozen mode, resolves relative to _MEIPASS."""
    fake_meipass = "/tmp/fake_meipass"
    monkeypatch.setattr(sys, "_MEIPASS", fake_meipass, raising=False)
    result = get_resource_path("arts")
    assert result == Path(fake_meipass) / "arts"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_resources.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement resource path helper**

Create `git_gui/resources.py`:

```python
import sys
from pathlib import Path

# Project root when running from source
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_resource_path(relative: str) -> Path:
    """Resolve a path relative to the project root or PyInstaller bundle."""
    if getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS) / relative
    return _PROJECT_ROOT / relative
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_resources.py -v`
Expected: PASS

- [ ] **Step 5: Update graph.py to use the helper**

In `git_gui/presentation/widgets/graph.py`, replace line 66:

```python
_ARTS = Path(__file__).resolve().parent.parent.parent.parent / "arts"
```

with:

```python
from git_gui.resources import get_resource_path

_ARTS = get_resource_path("arts")
```

And remove the now-unused `Path` import if it's no longer used elsewhere in the file. (Check first — `Path` is imported from `pathlib` at the top. If other code in the file still uses `Path`, keep the import.)

- [ ] **Step 6: Run all tests**

Run: `uv run pytest -v`
Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add git_gui/resources.py tests/test_resources.py git_gui/presentation/widgets/graph.py
git commit -m "feat: add resource path helper for PyInstaller compatibility"
```

---

### Task 2: PyInstaller spec file

**Files:**
- Create: `GitStack.spec`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add pyinstaller to dev dependencies**

In `pyproject.toml`, add `pyinstaller` to the dev dependency group:

```toml
[dependency-groups]
dev = [
    "pytest>=9.0.2",
    "pytest-qt>=4.5.0",
    "pyinstaller>=6.0",
]
```

- [ ] **Step 2: Install updated dependencies**

Run: `uv sync`

- [ ] **Step 3: Create the spec file**

Create `GitStack.spec`:

```python
# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('arts', 'arts'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
    cipher=block_cipher,
    collect_all=['pygit2'],
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GitStack',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='GitStack',
)
```

- [ ] **Step 4: Test the build locally**

Run: `uv run pyinstaller GitStack.spec`
Expected: `dist/GitStack/` directory created with the executable

- [ ] **Step 5: Verify the built app launches**

Run (Windows): `./dist/GitStack/GitStack.exe`
Run (macOS/Linux): `./dist/GitStack/GitStack`
Expected: GitStack opens with the repo picker dialog

- [ ] **Step 6: Add build artifacts to .gitignore**

Append to `.gitignore` (create if it doesn't exist):

```
# PyInstaller
build/
dist/
*.spec.bak
```

- [ ] **Step 7: Commit**

```bash
git add GitStack.spec pyproject.toml .gitignore
git commit -m "feat: add PyInstaller spec file for packaging"
```

---

### Task 3: GitHub Actions release workflow

**Files:**
- Create: `.github/workflows/release.yml`

- [ ] **Step 1: Create workflow directory**

```bash
mkdir -p .github/workflows
```

- [ ] **Step 2: Create the release workflow**

Create `.github/workflows/release.yml`:

```yaml
name: Release

on:
  push:
    tags:
      - 'v*'

permissions:
  contents: write

jobs:
  build:
    strategy:
      matrix:
        include:
          - os: windows-latest
            artifact: GitStack-windows
            archive_cmd: Compress-Archive -Path dist/GitStack/* -DestinationPath GitStack-windows.zip
            archive_ext: zip
            shell: pwsh
          - os: macos-latest
            artifact: GitStack-macos
            archive_cmd: tar -czf GitStack-macos.tar.gz -C dist GitStack
            archive_ext: tar.gz
            shell: bash
          - os: ubuntu-latest
            artifact: GitStack-linux
            archive_cmd: tar -czf GitStack-linux.tar.gz -C dist GitStack
            archive_ext: tar.gz
            shell: bash

    runs-on: ${{ matrix.os }}

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.13'

      - name: Install uv
        uses: astral-sh/setup-uv@v4

      - name: Install dependencies
        run: uv sync

      - name: Run tests
        run: uv run pytest -v

      - name: Install PyInstaller
        run: uv pip install pyinstaller

      - name: Build with PyInstaller
        run: uv run pyinstaller GitStack.spec

      - name: Archive build
        run: ${{ matrix.archive_cmd }}
        shell: ${{ matrix.shell }}

      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: ${{ matrix.artifact }}
          path: ${{ matrix.artifact }}.${{ matrix.archive_ext }}

  release:
    needs: build
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Download all artifacts
        uses: actions/download-artifact@v4
        with:
          path: artifacts

      - name: Create GitHub Release
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          tag="${GITHUB_REF#refs/tags/}"
          gh release create "$tag" \
            --title "GitStack $tag" \
            --generate-notes \
            artifacts/GitStack-windows/GitStack-windows.zip \
            artifacts/GitStack-macos/GitStack-macos.tar.gz \
            artifacts/GitStack-linux/GitStack-linux.tar.gz
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: add GitHub Actions release workflow for 3-platform packaging"
```

---

### Task 4: End-to-end verification

- [ ] **Step 1: Run all tests**

Run: `uv run pytest -v`
Expected: all tests PASS

- [ ] **Step 2: Test local build**

Run: `uv run pyinstaller GitStack.spec`
Expected: `dist/GitStack/` created, executable launches correctly

- [ ] **Step 3: Test release workflow (dry run)**

Push a test tag to trigger the workflow:

```bash
git tag v0.1.0-rc1
git push origin v0.1.0-rc1
```

Check GitHub Actions tab — all three platform builds should succeed and a draft release should appear with three archives.
