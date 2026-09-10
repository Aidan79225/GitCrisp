# Auto-updater Tier 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Notify the user via the log panel when a newer GitCrisp release is on GitHub, with a clickable Download link, gated by a `Help → Preferences...` checkbox.

**Architecture:** Pure `fetch_latest_release` function (sync, testable via `urllib` mock) wrapped by a `UpdateChecker` QObject that runs it on a `QThread` and emits `update_available(version, url)`. Settings stored via a tiny `app_settings` module that wraps `QSettings` so tests can mock cleanly. `LogPanel` body switches from `QPlainTextEdit` to `QTextBrowser` to support a new `log_link` method without changing existing `log`/`log_error`.

**Tech Stack:** Python 3.13, PySide6 (`QtNetwork` avoided — `urllib` + `QThread` is easier to test), `packaging.version.Version` for semver comparison. `uv run` for all commands.

**Spec:** `docs/superpowers/specs/2026-05-18-auto-updater-tier1-design.md`

---

## File Structure

| File | Purpose | Change |
|---|---|---|
| `git_gui/presentation/app_settings.py` | Tiny QSettings wrapper for application preferences | NEW |
| `git_gui/presentation/services/update_checker.py` | Async GitHub release check + signal emission | NEW |
| `git_gui/presentation/dialogs/preferences_dialog.py` | Modal preferences dialog with one checkbox | NEW |
| `git_gui/presentation/widgets/log_panel.py` | Log widget — switch body to `QTextBrowser`, add `log_link` | MODIFY |
| `git_gui/presentation/main_window/main_window.py` | Add `Help → Preferences...` menu, wire UpdateChecker on startup | MODIFY |
| `main.py` | Set `QCoreApplication.setOrganizationName("GitCrisp")` so QSettings has a stable path | MODIFY |
| `pyproject.toml` | Add `packaging>=24.0` to dependencies | MODIFY |
| `tests/presentation/test_app_settings.py` | Round-trip + default behavior | NEW |
| `tests/presentation/services/test_update_checker.py` | fetch_latest_release + UpdateChecker | NEW |
| `tests/presentation/dialogs/test_preferences_dialog.py` | Checkbox state + persistence | NEW |
| `tests/presentation/widgets/test_log_panel_link.py` | `log_link` renders + URL escaping | NEW |

Total: 7 source/config files, 4 test files.

---

## Task 1: Add `packaging` dependency

**Files:**
- Modify: `pyproject.toml` (dependencies list, around line 7-12)

- [ ] **Step 1: Add dependency**

Edit `pyproject.toml`:

```toml
dependencies = [
    "pygit2>=1.19.2,<2",
    "pyside6>=6.11.0,<7",
    "pygments>=2.17",
    "sentry-sdk>=2.0",
    "packaging>=24.0",
]
```

- [ ] **Step 2: Sync**

Run: `uv sync`
Expected: `packaging` resolves and is installed (may already be a transitive dep — that's fine, this makes ownership explicit).

- [ ] **Step 3: Sanity import check**

Run: `uv run python -c "from packaging.version import Version; print(Version('0.15.1') < Version('0.16.0'))"`
Expected: `True`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git -c user.name='Aidan Wang' -c user.email='aidan79225@gmail.com' commit -m "chore: pin packaging as explicit dep for version comparison"
```

---

## Task 2: Set OrganizationName so QSettings has a stable scope

**Files:**
- Modify: `main.py:57-62` (around the `app.setApplicationName("GitCrisp")` call)

QSettings keys its storage off `(OrganizationName, ApplicationName)`. Without an organization name, Qt warns and falls back to inconsistent paths.

- [ ] **Step 1: Add OrganizationName**

Find this block in `main.py`:

```python
    app = QApplication(sys.argv)
    app.setApplicationName("GitCrisp")
```

Change to:

```python
    app = QApplication(sys.argv)
    app.setOrganizationName("GitCrisp")
    app.setApplicationName("GitCrisp")
```

- [ ] **Step 2: Verify the existing test suite still passes**

Run: `uv run pytest tests/ -q`
Expected: 720+ passing, no new failures.

- [ ] **Step 3: Commit**

```bash
git add main.py
git -c user.name='Aidan Wang' -c user.email='aidan79225@gmail.com' commit -m "feat(main): set OrganizationName for stable QSettings scope"
```

---

## Task 3: `app_settings` module (TDD)

A tiny wrapper around `QSettings` so production code uses two functions and tests can mock at the module level (no need to swap Qt globals).

**Files:**
- Create: `git_gui/presentation/app_settings.py`
- Create: `tests/presentation/test_app_settings.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/presentation/test_app_settings.py`:

```python
"""Tests for the QSettings wrapper.

We swap QSettings' storage location to a tmp dir via setPath so tests
don't leak into the developer's real config.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication, QSettings


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    # Tests must use Ini format so setPath actually controls the file.
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QCoreApplication.setOrganizationName("GitCrispTest")
    QCoreApplication.setApplicationName("GitCrispTest")
    yield


def test_get_check_updates_defaults_to_true():
    from git_gui.presentation.app_settings import get_check_updates
    assert get_check_updates() is True


def test_set_then_get_round_trips_false():
    from git_gui.presentation.app_settings import get_check_updates, set_check_updates
    set_check_updates(False)
    assert get_check_updates() is False


def test_set_then_get_round_trips_true():
    from git_gui.presentation.app_settings import get_check_updates, set_check_updates
    set_check_updates(False)
    set_check_updates(True)
    assert get_check_updates() is True
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/presentation/test_app_settings.py -v`
Expected: `ImportError: cannot import name 'get_check_updates'`.

- [ ] **Step 3: Implement the module**

Create `git_gui/presentation/app_settings.py`:

```python
"""Application-wide preferences backed by QSettings.

Keys are namespaced under group prefixes so future settings stay
organized. Add new helpers here rather than poking QSettings directly
from feature modules so tests have a single mock surface.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings

_KEY_CHECK_UPDATES = "updates/check_on_startup"


def get_check_updates() -> bool:
    """Return whether the app should check for updates on startup. Default True."""
    return QSettings().value(_KEY_CHECK_UPDATES, True, type=bool)


def set_check_updates(value: bool) -> None:
    """Persist the update-check preference."""
    QSettings().setValue(_KEY_CHECK_UPDATES, value)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/presentation/test_app_settings.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/app_settings.py tests/presentation/test_app_settings.py
git -c user.name='Aidan Wang' -c user.email='aidan79225@gmail.com' commit -m "feat(settings): app_settings module wrapping QSettings"
```

---

## Task 4: `fetch_latest_release` pure function (TDD)

The sync HTTP+parse function. Tested by patching `urllib.request.urlopen` with stub bytes. Wrapped by `UpdateChecker` in Task 5.

**Files:**
- Create: `git_gui/presentation/services/update_checker.py` (function only — class added in Task 5)
- Create: `tests/presentation/services/test_update_checker.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/presentation/services/test_update_checker.py`:

```python
"""Tests for fetch_latest_release.

The function is sync and pure — mock urllib.request.urlopen with a
context manager whose .read() returns bytes.
"""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from git_gui.presentation.services.update_checker import fetch_latest_release


def _fake_response(payload: dict, status: int = 200):
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.status = status
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_returns_tag_and_url_on_success():
    payload = {
        "tag_name": "v0.16.0",
        "html_url": "https://github.com/Aidan79225/GitCrisp/releases/tag/v0.16.0",
    }
    with patch("urllib.request.urlopen", return_value=_fake_response(payload)):
        result = fetch_latest_release(
            "https://api.github.com/repos/Aidan79225/GitCrisp/releases/latest"
        )
    assert result == (
        "v0.16.0",
        "https://github.com/Aidan79225/GitCrisp/releases/tag/v0.16.0",
    )


def test_returns_none_on_network_error():
    with patch("urllib.request.urlopen", side_effect=URLError("DNS")):
        assert fetch_latest_release("https://api.github.com/...") is None


def test_returns_none_on_missing_keys():
    payload = {"tag_name": "v0.16.0"}  # no html_url
    with patch("urllib.request.urlopen", return_value=_fake_response(payload)):
        assert fetch_latest_release("https://api.github.com/...") is None


def test_returns_none_on_malformed_json():
    resp = MagicMock()
    resp.read.return_value = b"not-json"
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=resp):
        assert fetch_latest_release("https://api.github.com/...") is None
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/presentation/services/test_update_checker.py -v`
Expected: ImportError for `fetch_latest_release`.

- [ ] **Step 3: Implement the function**

Create `git_gui/presentation/services/update_checker.py`:

```python
"""GitHub release-check service.

Two layers:

- `fetch_latest_release`: pure sync function. Easy to test by patching
  `urllib.request.urlopen`. Returns ``(tag, html_url)`` or ``None`` for
  any failure (network, HTTP, JSON, missing fields).
- `UpdateChecker`: a QObject that runs ``fetch_latest_release`` on a
  background ``QThread`` and emits ``update_available(version, url)``
  when the remote version is newer than the running one. (Added in the
  next task.)
"""

from __future__ import annotations

import json
import logging
import urllib.request

logger = logging.getLogger(__name__)

LATEST_RELEASE_URL = (
    "https://api.github.com/repos/Aidan79225/GitCrisp/releases/latest"
)
_TIMEOUT_SECONDS = 5


def fetch_latest_release(url: str) -> tuple[str, str] | None:
    """Return ``(tag_name, html_url)`` for the latest release, or None on any failure."""
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT_SECONDS) as resp:
            body = resp.read()
    except Exception as e:
        logger.debug("Update check network error: %s", e)
        return None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        logger.debug("Update check JSON decode error: %s", e)
        return None
    tag = payload.get("tag_name")
    url_ = payload.get("html_url")
    if not isinstance(tag, str) or not isinstance(url_, str):
        logger.debug("Update check payload missing tag_name/html_url")
        return None
    return tag, url_
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/presentation/services/test_update_checker.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/services/update_checker.py tests/presentation/services/test_update_checker.py
git -c user.name='Aidan Wang' -c user.email='aidan79225@gmail.com' commit -m "feat(updates): fetch_latest_release sync helper"
```

---

## Task 5: `UpdateChecker` QObject + version comparison (TDD)

Wrap `fetch_latest_release` in a QObject that runs on a background `QThread` and emits `update_available` only when the remote version is strictly newer.

**Files:**
- Modify: `git_gui/presentation/services/update_checker.py` (add the class)
- Modify: `tests/presentation/services/test_update_checker.py` (add class tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/presentation/services/test_update_checker.py`:

```python
from unittest.mock import patch as _patch
import pytest


def test_update_checker_emits_when_remote_is_newer(qtbot):
    from git_gui.presentation.services.update_checker import UpdateChecker

    checker = UpdateChecker(current_version="0.15.1")
    fake_result = ("v0.16.0", "https://github.com/.../releases/tag/v0.16.0")
    with _patch(
        "git_gui.presentation.services.update_checker.fetch_latest_release",
        return_value=fake_result,
    ):
        with qtbot.waitSignal(checker.update_available, timeout=2000) as blocker:
            checker.check()
    assert blocker.args == ["v0.16.0", "https://github.com/.../releases/tag/v0.16.0"]


def test_update_checker_silent_when_remote_equal(qtbot):
    from git_gui.presentation.services.update_checker import UpdateChecker

    checker = UpdateChecker(current_version="0.16.0")
    received: list[tuple] = []
    checker.update_available.connect(lambda *a: received.append(a))
    with _patch(
        "git_gui.presentation.services.update_checker.fetch_latest_release",
        return_value=("v0.16.0", "https://..."),
    ):
        checker.check()
        qtbot.wait(200)
    assert received == []


def test_update_checker_silent_when_remote_older(qtbot):
    from git_gui.presentation.services.update_checker import UpdateChecker

    checker = UpdateChecker(current_version="0.16.0")
    received: list[tuple] = []
    checker.update_available.connect(lambda *a: received.append(a))
    with _patch(
        "git_gui.presentation.services.update_checker.fetch_latest_release",
        return_value=("v0.15.1", "https://..."),
    ):
        checker.check()
        qtbot.wait(200)
    assert received == []


def test_update_checker_silent_when_fetch_returns_none(qtbot):
    from git_gui.presentation.services.update_checker import UpdateChecker

    checker = UpdateChecker(current_version="0.15.1")
    received: list[tuple] = []
    checker.update_available.connect(lambda *a: received.append(a))
    with _patch(
        "git_gui.presentation.services.update_checker.fetch_latest_release",
        return_value=None,
    ):
        checker.check()
        qtbot.wait(200)
    assert received == []


def test_update_checker_silent_when_remote_tag_unparseable(qtbot):
    from git_gui.presentation.services.update_checker import UpdateChecker

    checker = UpdateChecker(current_version="0.15.1")
    received: list[tuple] = []
    checker.update_available.connect(lambda *a: received.append(a))
    with _patch(
        "git_gui.presentation.services.update_checker.fetch_latest_release",
        return_value=("nightly-foo", "https://..."),
    ):
        checker.check()
        qtbot.wait(200)
    assert received == []
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/presentation/services/test_update_checker.py -v`
Expected: 5 new tests FAIL with `ImportError: cannot import name 'UpdateChecker'`.

- [ ] **Step 3: Implement `UpdateChecker`**

Append to `git_gui/presentation/services/update_checker.py`:

```python
from packaging.version import InvalidVersion, Version
from PySide6.QtCore import QObject, QThread, Signal


class _CheckWorker(QObject):
    finished = Signal(object)  # tuple[str, str] | None

    def __init__(self, url: str) -> None:
        super().__init__()
        self._url = url

    def run(self) -> None:
        self.finished.emit(fetch_latest_release(self._url))


class UpdateChecker(QObject):
    """Background GitHub release check. Emits when a newer release is found.

    Owns its worker thread. ``check()`` is fire-and-forget; if you need
    to re-check later, just call it again.
    """

    update_available = Signal(str, str)  # (version_tag, html_url)

    def __init__(
        self,
        current_version: str,
        url: str = LATEST_RELEASE_URL,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._current_version = current_version
        self._url = url
        self._thread: QThread | None = None
        self._worker: _CheckWorker | None = None

    def check(self) -> None:
        self._thread = QThread(self)
        self._worker = _CheckWorker(self._url)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_finished(self, result: tuple[str, str] | None) -> None:
        if result is None:
            return
        tag, url = result
        try:
            remote = Version(tag.lstrip("v"))
            current = Version(self._current_version.lstrip("v"))
        except InvalidVersion as e:
            logger.debug("Update check version parse failed: %s", e)
            return
        if remote > current:
            self.update_available.emit(tag, url)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/presentation/services/test_update_checker.py -v`
Expected: all 9 PASS (4 from Task 4 + 5 new).

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/services/update_checker.py tests/presentation/services/test_update_checker.py
git -c user.name='Aidan Wang' -c user.email='aidan79225@gmail.com' commit -m "feat(updates): UpdateChecker QObject with version comparison"
```

---

## Task 6: `log_link` on LogPanel (refactor body to QTextBrowser, TDD)

**Files:**
- Modify: `git_gui/presentation/widgets/log_panel.py`
- Create: `tests/presentation/widgets/test_log_panel_link.py`

`QPlainTextEdit` doesn't render HTML hyperlinks. Swap the body to `QTextBrowser` (same API surface for what we use plus rich-text + clickable links via `setOpenExternalLinks`). Existing `log()` and `log_error()` keep using `insertText` with `QTextCharFormat` — that still works on `QTextBrowser` since it inherits from `QTextEdit`.

- [ ] **Step 1: Write the failing test**

Create `tests/presentation/widgets/test_log_panel_link.py`:

```python
"""Tests for LogPanel.log_link — clickable hyperlink rendering."""

from __future__ import annotations

from PySide6.QtWidgets import QTextBrowser

from git_gui.presentation.widgets.log_panel import LogPanel


def test_log_link_appends_hyperlink_html(qtbot):
    panel = LogPanel()
    qtbot.addWidget(panel)
    panel.log_link("New version available: v0.16.0", "https://example.com/r/v0.16.0")
    html = panel._body.toHtml()
    assert "https://example.com/r/v0.16.0" in html
    assert "New version available: v0.16.0" in html
    # Ensure it's wrapped in an anchor tag, not just text.
    assert "<a" in html.lower() and "href=" in html.lower()


def test_log_link_escapes_html_in_text(qtbot):
    """A text containing &/< must not break the document."""
    panel = LogPanel()
    qtbot.addWidget(panel)
    panel.log_link("v0.16.0 & friends", "https://example.com/?a=1&b=2")
    html = panel._body.toHtml()
    # The literal "&" in the text must be escaped, not embedded raw.
    assert "v0.16.0 &amp; friends" in html or "& friends" not in panel._body.toPlainText() or "v0.16.0 & friends" in panel._body.toPlainText()


def test_log_link_does_not_break_existing_log(qtbot):
    """Existing log()/log_error() output is still readable after refactor."""
    panel = LogPanel()
    qtbot.addWidget(panel)
    panel.log("Plain message")
    panel.log_error("An error")
    panel.log_link("Update available", "https://example.com")
    text = panel._body.toPlainText()
    assert "Plain message" in text
    assert "An error" in text
    assert "Update available" in text


def test_log_panel_body_is_qtextbrowser(qtbot):
    """The body must be a QTextBrowser so links are clickable / openExternalLinks works."""
    panel = LogPanel()
    qtbot.addWidget(panel)
    assert isinstance(panel._body, QTextBrowser)
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/presentation/widgets/test_log_panel_link.py -v`
Expected: tests FAIL. The first three fail with `AttributeError: 'LogPanel' object has no attribute 'log_link'`. The fourth fails because `_body` is `QPlainTextEdit`.

- [ ] **Step 3: Refactor body + add `log_link`**

Edit `git_gui/presentation/widgets/log_panel.py`:

(a) Change the import — replace `QPlainTextEdit` with `QTextBrowser`:

```python
from PySide6.QtWidgets import QLabel, QTextBrowser, QVBoxLayout, QWidget
```

(b) Change `_body` initialization (around lines 23-30):

```python
        self._body = QTextBrowser()
        self._body.setReadOnly(True)
        self._body.setLineWrapMode(QTextBrowser.NoWrap)
        self._body.setMaximumHeight(150)
        self._body.setOpenExternalLinks(True)
        font = self._body.font()
        font.setFamily("Courier New")
        self._body.setFont(font)
        self._body.setVisible(False)
```

(Removed the `QPlainTextEdit` reference; added `setOpenExternalLinks(True)` so hyperlinks open the system browser.)

(c) Add the `log_link` method after `log_error`:

```python
    def log_link(self, message: str, url: str) -> None:
        """Append a single row with ``message`` rendered as a clickable hyperlink to ``url``.

        Both the message text and the URL are HTML-escaped so they cannot
        inject markup. The row uses the default foreground color and the
        same timestamp prefix as ``log()``.
        """
        from html import escape

        ts = datetime.now().strftime("%H:%M:%S")
        safe_msg = escape(message)
        safe_url = escape(url, quote=True)
        c = get_theme_manager().current.colors
        color = c.as_qcolor("primary").name()
        cursor = self._body.textCursor()
        cursor.movePosition(QTextCursor.End)
        if self._body.document().characterCount() > 1:
            cursor.insertBlock()
        cursor.insertHtml(
            f'<span style="color: {c.on_surface};">[{ts}] </span>'
            f'<a href="{safe_url}" style="color: {color};">{safe_msg}</a>'
        )
        self._body.setTextCursor(cursor)
        self._body.ensureCursorVisible()
```

- [ ] **Step 4: Run new + existing log panel tests**

Run:
```
uv run pytest tests/presentation/widgets/test_log_panel_link.py tests/presentation/widgets/test_log_panel.py -v
```

(If `test_log_panel.py` doesn't exist, just run the link one.)
Expected: all 4 new tests PASS. Any pre-existing log panel tests still PASS.

- [ ] **Step 5: Full-suite regression check**

Run: `uv run pytest tests/ -q`
Expected: all green. Watch in particular for any test that asserts on `panel._body` being a `QPlainTextEdit` (rename or update if found).

- [ ] **Step 6: Commit**

```bash
git add git_gui/presentation/widgets/log_panel.py tests/presentation/widgets/test_log_panel_link.py
git -c user.name='Aidan Wang' -c user.email='aidan79225@gmail.com' commit -m "feat(log-panel): add log_link with clickable hyperlink (body → QTextBrowser)"
```

---

## Task 7: `PreferencesDialog` (TDD)

**Files:**
- Create: `git_gui/presentation/dialogs/preferences_dialog.py`
- Create: `tests/presentation/dialogs/test_preferences_dialog.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/presentation/dialogs/test_preferences_dialog.py`:

```python
"""Tests for PreferencesDialog."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QDialog


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path):
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QCoreApplication.setOrganizationName("GitCrispTest")
    QCoreApplication.setApplicationName("GitCrispTest")
    yield


def test_dialog_checkbox_reflects_current_setting_true(qtbot):
    from git_gui.presentation.app_settings import set_check_updates
    from git_gui.presentation.dialogs.preferences_dialog import PreferencesDialog

    set_check_updates(True)
    dlg = PreferencesDialog()
    qtbot.addWidget(dlg)
    assert dlg._check_updates_box.isChecked() is True


def test_dialog_checkbox_reflects_current_setting_false(qtbot):
    from git_gui.presentation.app_settings import set_check_updates
    from git_gui.presentation.dialogs.preferences_dialog import PreferencesDialog

    set_check_updates(False)
    dlg = PreferencesDialog()
    qtbot.addWidget(dlg)
    assert dlg._check_updates_box.isChecked() is False


def test_accept_persists_change(qtbot):
    from git_gui.presentation.app_settings import get_check_updates, set_check_updates
    from git_gui.presentation.dialogs.preferences_dialog import PreferencesDialog

    set_check_updates(True)
    dlg = PreferencesDialog()
    qtbot.addWidget(dlg)
    dlg._check_updates_box.setChecked(False)
    dlg.accept()
    assert get_check_updates() is False


def test_reject_does_not_persist(qtbot):
    from git_gui.presentation.app_settings import get_check_updates, set_check_updates
    from git_gui.presentation.dialogs.preferences_dialog import PreferencesDialog

    set_check_updates(True)
    dlg = PreferencesDialog()
    qtbot.addWidget(dlg)
    dlg._check_updates_box.setChecked(False)
    dlg.reject()
    assert get_check_updates() is True
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/presentation/dialogs/test_preferences_dialog.py -v`
Expected: `ImportError` for `PreferencesDialog`.

- [ ] **Step 3: Implement the dialog**

Create `git_gui/presentation/dialogs/preferences_dialog.py`:

```python
"""Application preferences dialog.

Today: a single ``Check for updates on startup`` checkbox. Designed to
grow — future preferences (Sentry opt-out, language, etc.) plug into
the same form layout.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QVBoxLayout,
    QWidget,
)

from git_gui.presentation.app_settings import get_check_updates, set_check_updates


class PreferencesDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setModal(True)

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self._check_updates_box = QCheckBox("Check for updates on startup")
        self._check_updates_box.setChecked(get_check_updates())
        form.addRow(self._check_updates_box)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        set_check_updates(self._check_updates_box.isChecked())
        super().accept()
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/presentation/dialogs/test_preferences_dialog.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/dialogs/preferences_dialog.py tests/presentation/dialogs/test_preferences_dialog.py
git -c user.name='Aidan Wang' -c user.email='aidan79225@gmail.com' commit -m "feat(dialog): PreferencesDialog with update-check toggle"
```

---

## Task 8: Wire UpdateChecker + Preferences menu into MainWindow

**Files:**
- Modify: `git_gui/presentation/main_window/main_window.py`

This task has no failing-test-first because it's wiring (and Qt menu wiring is awkward to unit-test in isolation). Coverage comes from the manual smoke test plus the unit tests of each component already written.

- [ ] **Step 1: Read main_window.py to find the menu-bar wiring location**

Run: `uv run python -c "from git_gui.presentation.main_window.main_window import MainWindow; import inspect; print(inspect.getsourcefile(MainWindow))"` and open the file.

Grep for `menuBar()` and `addMenu` in `git_gui/presentation/main_window/main_window.py` to find where menus are added. If there's no Help menu, add one.

- [ ] **Step 2: Add the Preferences menu action**

In `MainWindow.__init__` (or whichever method builds the menus), after the existing menu setup, add:

```python
        help_menu = self.menuBar().addMenu("&Help")
        prefs_action = help_menu.addAction("Preferences...")
        prefs_action.triggered.connect(self._open_preferences)
```

If a `&Help` menu already exists, append the `Preferences...` action to it instead of adding a new one.

Then add the handler method:

```python
    def _open_preferences(self) -> None:
        from git_gui.presentation.dialogs.preferences_dialog import PreferencesDialog
        dlg = PreferencesDialog(self)
        dlg.exec()
```

- [ ] **Step 3: Add the startup update check**

In `MainWindow.__init__`, after the main widgets are created (toward the end of `__init__`, after `self._log_panel` is constructed):

```python
        from git_gui.observability import _get_version
        from git_gui.presentation.app_settings import get_check_updates
        from git_gui.presentation.services.update_checker import UpdateChecker

        if get_check_updates() and _get_version() != "unknown":
            self._update_checker = UpdateChecker(_get_version(), parent=self)
            self._update_checker.update_available.connect(self._on_update_available)
            self._update_checker.check()
```

And the handler:

```python
    def _on_update_available(self, version: str, url: str) -> None:
        self._log_panel.log_link(f"New version available: {version} — Download", url)
```

- [ ] **Step 4: Smoke test that nothing crashes on startup**

Run: `uv run python main.py`
Expected: app opens normally (no UpdateChecker traceback in the console). Close it.

If you're on a dev build (`_get_version()` returns `"unknown"`), the checker is skipped — confirm with `uv run python -c "from git_gui.observability import _get_version; print(_get_version())"` (likely prints `0.1.0` from `pyproject.toml`, which is the installed package version when `uv sync` is used — that's still a valid Version and the check WILL run; remote release `v0.10.0`+ will likely be newer, so a real toast may appear in the log panel. That's expected behavior in a dev environment).

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/ -q`
Expected: all green. No crashes from `MainWindow` constructor changes.

- [ ] **Step 6: All four gates**

Run sequentially:
```
uv run ruff check .
uv run ruff format --check .
uv run mypy git_gui/domain git_gui/application
uv run pytest tests/ -q
```
All must be green.

- [ ] **Step 7: Commit**

```bash
git add git_gui/presentation/main_window/main_window.py
git -c user.name='Aidan Wang' -c user.email='aidan79225@gmail.com' commit -m "feat(main): wire UpdateChecker + Help → Preferences..."
```

---

## Task 9: Manual smoke test + push + PR

- [ ] **Step 1: Manual smoke test**

Run: `uv run python main.py`

1. Wait a few seconds. If a newer release exists on GitHub, expect a row in the log panel saying "New version available: vX.Y.Z — Download" with "Download" rendered as a clickable link.
2. Click the link → browser opens to `https://github.com/Aidan79225/GitCrisp/releases/tag/vX.Y.Z`.
3. Open `Help → Preferences...` → see the dialog with one checkbox, currently checked.
4. Uncheck → OK → close app → reopen → no update check happens (no log row).
5. Re-open `Help → Preferences...` → checkbox is unchecked → check → OK → close + reopen → check happens again.
6. Briefly disconnect network → close + reopen app → no error in log panel, no crash. (The debug log entry at `~/.gitcrisp/logs/gitcrisp.log` is the only trace.)

- [ ] **Step 2: Push**

```bash
git push -u origin feat/auto-updater-tier1
```

- [ ] **Step 3: Open PR**

```bash
gh pr create --title "feat: auto-updater Tier 1 — notify when new release is available" --body "$(cat <<'EOF'
## Summary

On startup, GitCrisp now checks GitHub for a newer release and surfaces a single log-panel row with a clickable Download link if one exists. The check is async (UI never blocks), silent on failure (offline, rate-limited, malformed payload all stay invisible), and can be disabled via Help → Preferences....

Spec: `docs/superpowers/specs/2026-05-18-auto-updater-tier1-design.md`

## Why this version (Tier 1)

Tier 2 (in-app download) and Tier 3 (auto-apply) require platform-specific elevation, code-signing flows, and a full update-server protocol — too much for a single PR and very little marginal value over "click here to download". Spyder, Picard, and Anki all started here. We can revisit Tier 2 if we ever ship updates so often that downloads become friction.

## Architecture

- `fetch_latest_release(url) -> (tag, html_url) | None` — pure sync function, `urllib.request`-based. Easy to unit test by patching `urlopen`.
- `UpdateChecker(QObject)` — runs the fetch on a `QThread`, parses with `packaging.version.Version`, emits `update_available(version, url)` only when remote > current.
- `app_settings.get_check_updates() / set_check_updates(bool)` — thin QSettings wrapper. Default `True`.
- `LogPanel.log_link(msg, url)` — new method, HTML-escaped. Body refactored from `QPlainTextEdit` to `QTextBrowser` for hyperlink rendering.
- `PreferencesDialog` — modal, single checkbox today, designed to grow.

Failure modes (network, HTTP, JSON, parse, dev build, opt-out) all silently skip — only positive log line is "you have a new version".

## Test plan
- [x] 3 tests for `app_settings`
- [x] 9 tests for `update_checker` (4 fetch + 5 UpdateChecker scenarios)
- [x] 4 tests for `log_panel.log_link`
- [x] 4 tests for `PreferencesDialog`
- [x] Full suite still green; ruff / mypy clean
- [ ] Manual: open app, see toast, click link, browser opens
- [ ] Manual: disable in Preferences, restart, no toast
- [ ] Manual: airplane mode, restart, no crash

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage:**
- ✅ Async check on every startup → Task 5 (`UpdateChecker` uses `QThread`) + Task 8 wiring
- ✅ Log panel row with clickable Download link → Task 6
- ✅ `Help → Preferences...` with checkbox → Task 7 + Task 8
- ✅ QSettings storage → Task 3
- ✅ Dev-build skip (`VERSION == "unknown"`) → Task 8 wiring guard
- ✅ Offline / HTTP error / malformed JSON silent → Task 4
- ✅ Version comparison via `packaging.Version` → Task 5
- ✅ `packaging` explicit dependency → Task 1
- ✅ Pre-release filter (auto via `/latest`) → no extra task needed
- ✅ `setOrganizationName` for QSettings stability → Task 2

**Placeholder scan:** No "TBD" or "implement later"; every code step has the actual code.

**Type consistency:**
- `update_available = Signal(str, str)` — declared in Task 5, consumed in Task 8 handler. ✓
- `fetch_latest_release(url) -> tuple[str, str] | None` — defined Task 4, called by `_CheckWorker` in Task 5. ✓
- `get_check_updates() -> bool` / `set_check_updates(value: bool)` — defined Task 3, used by Tasks 7 and 8. ✓
- `log_link(message, url)` — defined Task 6, called by Task 8 handler. ✓

One implementation detail flagged during writing: the existing `LogPanel._rebuild_styles` does a `cursor.mergeCharFormat(self._fmt_default)` over the whole document. After the refactor to `QTextBrowser`, this will overwrite the hyperlink color when the theme changes — the hyperlink stays clickable but loses its `primary`-colored styling. The implementer should be aware: if this matters, `_rebuild_styles` will need a small extension to re-color anchor tags via CSS (`a { color: ...; }` in the document's default stylesheet). Not in scope for this plan; defer to a follow-up if visible.
