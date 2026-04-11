# File Logging + Warning Instrumentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal stdlib-only rotating file logger and convert the 12 bare `except Exception` sites in `pygit2_repo.py` into WARNING-level log calls, so silent failures become diagnosable.

**Architecture:** A new `git_gui/logging_setup.py` module exposes a single idempotent `setup_logging()` function that installs one `RotatingFileHandler` on the root logger writing to `~/.gitcrisp/logs/gitcrisp.log`. `main.py` calls it before `QApplication(sys.argv)`. `pygit2_repo.py` gains a module-level `logger = logging.getLogger(__name__)` and each bare-except site logs a WARNING before returning its existing fallback value.

**Tech Stack:** Python stdlib `logging` only. No new dependencies. pytest + uv for tests.

**Spec:** `docs/superpowers/specs/2026-04-11-file-logging-design.md`

---

## File Structure

**New:**
- `git_gui/logging_setup.py` — the `setup_logging()` function and the hard-coded constants (`_LOG_DIR`, `_LOG_FILE`, `_MAX_BYTES`, `_BACKUP_COUNT`).
- `tests/test_logging_setup.py` — unit tests for `setup_logging()`.

**Modified:**
- `main.py` — import `setup_logging` and call it first inside `main()`.
- `git_gui/infrastructure/pygit2_repo.py` — add module logger; replace 12 bare-except sites with warning-logged equivalents.

---

## Task 1: Create `logging_setup.py` module (TDD)

**Files:**
- Create: `git_gui/logging_setup.py`
- Create: `tests/test_logging_setup.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_logging_setup.py` with the following content:

```python
"""Tests for the logging_setup module."""
from __future__ import annotations
import logging
import logging.handlers
from pathlib import Path

import pytest

from git_gui import logging_setup


@pytest.fixture(autouse=True)
def _reset_root_logger():
    """Snapshot and restore the root logger around each test.

    setup_logging() mutates global state, so we need to clean up afterwards
    to avoid leaking handlers into other tests.
    """
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    yield
    # Remove any handlers added during the test
    for handler in list(root.handlers):
        if handler not in original_handlers:
            handler.close()
            root.removeHandler(handler)
    root.setLevel(original_level)


def _point_log_dir_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect logging_setup's log file into tmp_path for isolation."""
    log_dir = tmp_path / "logs"
    log_file = log_dir / "gitcrisp.log"
    monkeypatch.setattr(logging_setup, "_LOG_DIR", log_dir)
    monkeypatch.setattr(logging_setup, "_LOG_FILE", log_file)
    return log_file


def test_setup_logging_creates_file(tmp_path, monkeypatch):
    log_file = _point_log_dir_at(tmp_path, monkeypatch)

    logging_setup.setup_logging()

    logger = logging.getLogger("test.creates_file")
    logger.warning("hello from test_setup_logging_creates_file")
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "hello from test_setup_logging_creates_file" in content
    assert "WARNING" in content
    assert "test.creates_file" in content


def test_setup_logging_is_idempotent(tmp_path, monkeypatch):
    _point_log_dir_at(tmp_path, monkeypatch)

    logging_setup.setup_logging()
    logging_setup.setup_logging()
    logging_setup.setup_logging()

    root = logging.getLogger()
    rotating_handlers = [
        h for h in root.handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(rotating_handlers) == 1


def test_setup_logging_ignores_debug_by_default(tmp_path, monkeypatch):
    log_file = _point_log_dir_at(tmp_path, monkeypatch)

    logging_setup.setup_logging()

    logger = logging.getLogger("test.debug_filter")
    logger.debug("debug-should-not-appear")
    logger.warning("warning-should-appear")
    for handler in logging.getLogger().handlers:
        handler.flush()

    content = log_file.read_text(encoding="utf-8")
    assert "debug-should-not-appear" not in content
    assert "warning-should-appear" in content
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `uv run pytest tests/test_logging_setup.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'git_gui.logging_setup'`.

- [ ] **Step 3: Create the module**

Create `git_gui/logging_setup.py`:

```python
"""Minimal file-logging setup for GitCrisp.

A single rotating file handler on the root logger, writing to
``~/.gitcrisp/logs/gitcrisp.log``. Called once from ``main.main()``
before the ``QApplication`` starts.

Idempotent — calling ``setup_logging()`` multiple times is safe and
will not install duplicate handlers.
"""
from __future__ import annotations
import logging
import logging.handlers
from pathlib import Path

_LOG_DIR = Path.home() / ".gitcrisp" / "logs"
_LOG_FILE = _LOG_DIR / "gitcrisp.log"
_MAX_BYTES = 1_000_000  # 1 MB per file
_BACKUP_COUNT = 3       # keep gitcrisp.log.1 .. .3


def setup_logging() -> None:
    """Configure the root logger with a single rotating file handler.

    Idempotent — calling it twice does not install duplicate handlers.
    """
    root = logging.getLogger()
    if any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        return

    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        _LOG_FILE,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    ))
    root.setLevel(logging.WARNING)
    root.addHandler(handler)
```

- [ ] **Step 4: Run the tests again and confirm they pass**

Run: `uv run pytest tests/test_logging_setup.py -v`

Expected: All 3 tests PASS.

- [ ] **Step 5: Run the full suite to confirm nothing regressed**

Run: `uv run pytest tests/ -x -q`

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add git_gui/logging_setup.py tests/test_logging_setup.py
git commit -m "feat(logging): add idempotent rotating file logger setup"
```

---

## Task 2: Wire `setup_logging()` into `main.py`

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add the import**

In `main.py`, add this import line right after the existing `from git_gui.presentation.theme import ...` line:

```python
from git_gui.logging_setup import setup_logging
```

- [ ] **Step 2: Call `setup_logging()` at the top of `main()`**

In `main.py`, update the `main()` function. The current first line is:

```python
def main() -> None:
    app = QApplication(sys.argv)
```

Change it to:

```python
def main() -> None:
    setup_logging()
    app = QApplication(sys.argv)
```

- [ ] **Step 3: Smoke check the import**

Run: `uv run python -c "import main; print('ok')"`

Expected: `ok`

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest tests/ -x -q`

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat(main): call setup_logging() before QApplication"
```

---

## Task 3: Add module logger + instrument first batch of bare-except sites

This task covers the bare-except sites inside the diff-related reader methods. There are 6 sites in this batch. Each one gets the same treatment: replace `except Exception: ...` with `except Exception as e: logger.warning(...); ...`, keeping the existing fallback value.

**Files:**
- Modify: `git_gui/infrastructure/pygit2_repo.py`

- [ ] **Step 1: Add the module logger**

In `git_gui/infrastructure/pygit2_repo.py`, add these two lines to the import block near the top of the file (after the existing stdlib imports, before the `import pygit2` line if possible; otherwise just below `from git_gui.resources import subprocess_kwargs`):

```python
import logging

logger = logging.getLogger(__name__)
```

- [ ] **Step 2: Instrument `get_branches` — line 187**

Current code:

```python
    def get_branches(self) -> list[Branch]:
        branches: list[Branch] = []
        try:
            head_ref_name = self._repo.head.name if not self._repo.head_is_unborn else None
        except Exception:
            head_ref_name = None
```

Replace with:

```python
    def get_branches(self) -> list[Branch]:
        branches: list[Branch] = []
        try:
            head_ref_name = self._repo.head.name if not self._repo.head_is_unborn else None
        except Exception as e:
            logger.warning("Failed to read HEAD ref name: %s", e)
            head_ref_name = None
```

- [ ] **Step 3: Instrument `get_working_tree_diff_map` staged side — line 313**

Current code (inside the "Staged: index vs HEAD" block):

```python
            for patch in staged_diff:
                path = patch.delta.new_file.path or patch.delta.old_file.path
                if not path:
                    continue
                result.setdefault(path, {"staged": [], "unstaged": []})
                result[path]["staged"] = _diff_to_hunks(patch)
        except Exception:
            pass
```

Replace the `except` clause with:

```python
        except Exception as e:
            logger.warning("Failed to compute staged diff map: %s", e)
```

- [ ] **Step 4: Instrument `get_working_tree_diff_map` unstaged side — line 337**

Current code (inside the "Unstaged: workdir vs index" block):

```python
                result[path]["unstaged"] = hunks
        except Exception:
            pass
```

Replace the `except` clause with:

```python
        except Exception as e:
            logger.warning("Failed to compute unstaged diff map: %s", e)
```

- [ ] **Step 5: Instrument `get_working_tree_diff_map` untracked side — line 346**

Current code:

```python
        # Untracked files
        try:
            for path, status in self._repo.status().items():
                if status & pygit2.GIT_STATUS_WT_NEW:
                    result.setdefault(path, {"staged": [], "unstaged": []})
                    result[path]["unstaged"] = _synthesise_untracked_hunk(self._repo.workdir, path)
        except Exception:
            pass
```

Replace the `except` clause with:

```python
        except Exception as e:
            logger.warning("Failed to enumerate untracked files for diff map: %s", e)
```

- [ ] **Step 6: Instrument `_diff_workfile_against_head` — line 359**

Current code:

```python
    def _diff_workfile_against_head(self, path: str) -> list[Hunk]:
        """Diff the working-tree file against the HEAD version."""
        try:
            head_commit = self._repo.head.peel(pygit2.Commit)
            diff = self._repo.diff(head_commit.tree, flags=pygit2.GIT_DIFF_FORCE_TEXT)
            for patch in diff:
                if patch.delta.new_file.path == path or patch.delta.old_file.path == path:
                    return _diff_to_hunks(patch)
        except Exception:
            pass
        return []
```

Replace the `except` clause with:

```python
        except Exception as e:
            logger.warning("Failed to diff %r against HEAD: %s", path, e)
```

- [ ] **Step 7: Instrument `get_staged_diff` — line 378**

Current code (inside `get_staged_diff`):

```python
            for patch in diff:
                if patch.delta.new_file.path == path or patch.delta.old_file.path == path:
                    return _diff_to_hunks(patch)
        except Exception:
            pass
        return []
```

Replace the `except` clause with:

```python
        except Exception as e:
            logger.warning("Failed to compute staged diff for %r: %s", path, e)
```

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest tests/ -x -q`

Expected: All pass. Nothing in the test suite should care that these paths now log a warning when they fail.

- [ ] **Step 9: Commit**

```bash
git add git_gui/infrastructure/pygit2_repo.py
git commit -m "feat(infra): log warnings for silent failures in diff readers"
```

---

## Task 4: Instrument second batch of bare-except sites

This task covers the remaining 6 bare-except sites in `pygit2_repo.py`: remote tags, commit stats, three sites in `list_submodules`, and one in `list_local_branches_with_upstream`.

**Files:**
- Modify: `git_gui/infrastructure/pygit2_repo.py`

- [ ] **Step 1: Instrument `get_remote_tags` — line 440**

Current code:

```python
            return tags
        except Exception:
            return []
```

Replace the `except` clause with:

```python
        except Exception as e:
            logger.warning("Failed to list remote tags for %r: %s", remote, e)
            return []
```

- [ ] **Step 2: Instrument `get_commit_stats` — line 456**

Current code:

```python
            if result.returncode != 0:
                return []
        except Exception:
            return []
```

Replace the `except` clause with:

```python
        except Exception as e:
            logger.warning("Failed to run git log for commit stats: %s", e)
            return []
```

- [ ] **Step 3: Instrument `list_submodules` — line 976 (listall_submodules)**

Current code:

```python
    def list_submodules(self) -> list[Submodule]:
        result: list[Submodule] = []
        try:
            sm_paths = list(self._repo.listall_submodules())
        except Exception:
            return result
```

Replace the `except` clause with:

```python
        except Exception as e:
            logger.warning("Failed to list submodules: %s", e)
            return result
```

- [ ] **Step 4: Instrument `list_submodules` — line 994 (.gitmodules parse)**

Current code (inside the `if os.path.exists(gitmodules_path):` block):

```python
            try:
                cfg = pygit2.Config(gitmodules_path)
                for entry in cfg:
                    # entry.name is like "submodule.libs/foo.url"
                    parts = entry.name.split(".")
                    if len(parts) >= 3 and parts[0] == "submodule" and parts[-1] == "url":
                        sm_path = ".".join(parts[1:-1])
                        url_map[sm_path] = entry.value
            except Exception:
                pass
```

Replace the `except` clause with:

```python
            except Exception as e:
                logger.warning("Failed to parse .gitmodules at %r: %s", gitmodules_path, e)
```

- [ ] **Step 5: Instrument `list_submodules` — line 1012 (git ls-files subprocess)**

Current code:

```python
        try:
            ls_result = subprocess.run(
                ["git", "ls-files", "-s", "--"] + sm_paths,
                capture_output=True, text=True,
                cwd=self._repo.workdir, **subprocess_kwargs(),
            )
            for line in ls_result.stdout.splitlines():
                # Format: "160000 <sha> <stage>\t<path>"
                line_parts = line.split("\t", 1)
                if len(line_parts) == 2:
                    fields = line_parts[0].split()
                    if len(fields) >= 2 and fields[0] == "160000":
                        sha_map[line_parts[1]] = fields[1]
        except Exception:
            pass
```

Replace the `except` clause with:

```python
        except Exception as e:
            logger.warning("Failed to read submodule SHAs via git ls-files: %s", e)
```

- [ ] **Step 6: Instrument `list_local_branches_with_upstream` — line 1038**

Current code (inside the loop over local branches):

```python
            try:
                upstream = br.upstream.shorthand if br.upstream else None
            except Exception:
                upstream = None
```

Replace the `except` clause with:

```python
            except Exception as e:
                logger.warning("Failed to read upstream for branch %r: %s", name, e)
                upstream = None
```

- [ ] **Step 7: Verify no bare `except Exception: pass` sites remain in `pygit2_repo.py`**

Run a grep to confirm there are no bare-pass or bare-fallback-without-log sites left:

Run: `uv run python -c "import re; text = open('git_gui/infrastructure/pygit2_repo.py').read(); matches = re.findall(r'except Exception:\s*\n\s*(pass|return)', text); print('remaining bare-except sites:', len(matches))"`

Expected: `remaining bare-except sites: 0`

If the output is not zero, grep for `except Exception:` and inspect any remaining site — it may be a valid named-exception handler that the earlier grep missed, or a site that still needs conversion.

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest tests/ -x -q`

Expected: All pass.

- [ ] **Step 9: Commit**

```bash
git add git_gui/infrastructure/pygit2_repo.py
git commit -m "feat(infra): log warnings for silent failures in remote, submodule, and branch readers"
```

---

## Task 5: Manual acceptance

- [ ] **Step 1: Delete any pre-existing log file (optional)**

Run the app once on a real repo without touching the log. Then check whether `~/.gitcrisp/logs/gitcrisp.log` was created during startup.

Run: `uv run python main.py`

Close the app. Then:

Run: `ls -la ~/.gitcrisp/logs/` (or `dir %USERPROFILE%\.gitcrisp\logs` on cmd, or `ls ~/.gitcrisp/logs/` in Git Bash)

Expected: The directory exists and contains an empty or small `gitcrisp.log` file. An empty file is correct — on a healthy repo nothing logs.

- [ ] **Step 2: Trigger a warning path**

Open a repo that has at least one submodule. Break the `.gitmodules` file temporarily (e.g., rename it or append invalid config). Launch the app.

Run: `uv run python main.py`

After the main window loads, navigate to a view that reads submodules (the working tree or sidebar). Close the app.

Read the log file.

Run: `cat ~/.gitcrisp/logs/gitcrisp.log` (or use your editor)

Expected: At least one `WARNING` line mentioning `pygit2_repo` and the submodule-related operation (`Failed to parse .gitmodules ...` or `Failed to list submodules: ...`).

Restore `.gitmodules` after testing.

- [ ] **Step 3: Confirm app behavior is unchanged**

With `.gitmodules` restored, run the app again and verify that normal diff / commit / merge workflows still work exactly as before. The logger should not change any user-visible behavior.

- [ ] **Step 4: Confirm rotation works on the happy path**

Append ~5 MB of artificial WARNING entries via a small one-liner (only if you want to exercise rotation — optional):

Run:

```bash
uv run python -c "from git_gui.logging_setup import setup_logging; import logging; setup_logging(); log = logging.getLogger('manual.test'); [log.warning('x' * 1000) for _ in range(5000)]"
```

Then:

Run: `ls ~/.gitcrisp/logs/`

Expected: See `gitcrisp.log`, `gitcrisp.log.1`, `gitcrisp.log.2`, `gitcrisp.log.3` (or however many backups the rotation created — up to 3).

- [ ] **Step 5: Commit any follow-up fixes**

If manual testing reveals anything unexpected, fix and commit with a descriptive message.

---

## Out of Scope

- In-app log viewer / menu item.
- Env-var or runtime toggles to change the log level.
- Log file path customisation.
- Routing Qt-internal messages (`qInstallMessageHandler`) through the logger.
- Replacing bare-except sites outside `pygit2_repo.py` (presentation layer is not in this spec).
- Reworking the `LogPanel` widget.
