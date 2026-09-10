# Auto-updater Tier 1 — design

A non-intrusive notification when a new GitCrisp release is available on GitHub. The user manually downloads the new installer; the app does not download or apply updates itself. Tier 1 in the analysis at `docs/superpowers/plans/...` is the "notify only" tier — matches what Spyder, Picard, and Anki shipped first.

## Goals

- On every app startup, check `GET /repos/Aidan79225/GitCrisp/releases/latest` asynchronously (do not block UI).
- If the remote release tag is newer than the running version, surface a single log entry in the log panel with a clickable "Download" link that opens the GitHub releases page.
- Users can disable the check via `Help → Preferences...` (a new dialog containing one checkbox for now).
- The check never causes a visible failure: offline, rate-limited, and DNS-failed cases all stay silent in the UI.
- Dev runs (`uv run python main.py`) skip the check entirely — they have no meaningful version to compare against.

## Non-goals

- Downloading the installer in-app (Tier 2).
- Applying the update automatically (Tier 3).
- Showing pre-releases — GitHub's `/releases/latest` endpoint already excludes them, no extra filtering.
- Notifying about beta/RC versions.
- A general-purpose Preferences UI beyond the single checkbox added here. Future settings (telemetry, language) can grow into the same dialog later.
- Telling the user *what* changed in the new version. The link opens the releases page where they can read the notes themselves.

## Architecture

A single new `UpdateChecker` service (no UI, just signal-emitting) plus a thin Preferences dialog and one new log-panel method for clickable links.

```
                            ┌────────────────────┐
   MainWindow.__init__ ───▶ │   UpdateChecker    │
                            │  (QObject)         │
                            │                    │
                            │  check() — async   │
                            │  via QtNetwork     │
                            │                    │
                            │  signal:           │
                            │   update_available │
                            │   (version, url)   │
                            └─────────┬──────────┘
                                      │ emit
                                      ▼
                        MainWindow._on_update_available
                                      │
                                      ▼
                          log_panel.log_link(...)
```

`Help → Preferences...` opens a modal `PreferencesDialog` with one `QCheckBox` ("Check for updates on startup"). Persistence: `QSettings` (Qt's cross-platform key-value store).

## Components

### `git_gui/presentation/services/update_checker.py` (new)

A `QObject` that owns a `QNetworkAccessManager`:

```python
class UpdateChecker(QObject):
    update_available = Signal(str, str)  # (version, html_url)

    def __init__(self, current_version: str, parent: QObject | None = None) -> None: ...

    def check(self) -> None:
        """Fire one async request to /releases/latest. Caller wires the signal."""
```

The service performs version comparison via `packaging.version.Version`:

```python
if Version(remote_tag.lstrip("v")) > Version(current_version):
    self.update_available.emit(remote_tag, html_url)
```

Failure modes all log at `logger.debug` and silently return: network error, non-2xx HTTP, missing fields in the JSON, version parse error.

### `git_gui/presentation/dialogs/preferences_dialog.py` (new)

```python
class PreferencesDialog(QDialog):
    """Application preferences. Single setting today: update check.

    Designed to grow — future entries are stacked vertically in the same form.
    """
```

Layout: a `QFormLayout` (or vertical) with one `QCheckBox("Check for updates on startup")`. OK / Cancel buttons. On OK, write through `QSettings`.

### `git_gui/presentation/widgets/log_panel.py` (modify)

Add a `log_link(text: str, url: str)` method that inserts a new log row rendered as an HTML hyperlink. Implementation uses the existing log-row factory but with a `QLabel` that has `setOpenExternalLinks(True)` and `setTextFormat(Qt.RichText)` instead of a plain text label. URL escaping happens here.

### `git_gui/presentation/main_window/main_window.py` (or a new lifecycle mixin)

In `__init__`, after the main widgets are created:

```python
if QSettings().value("updates/check_on_startup", True, type=bool):
    if _get_version() != "unknown":
        self._update_checker = UpdateChecker(_get_version(), parent=self)
        self._update_checker.update_available.connect(self._on_update_available)
        self._update_checker.check()
```

Where `_get_version()` is `git_gui.observability._get_version` (already exists). The dev-build guard is the `!= "unknown"` check.

`_on_update_available(version, url)` calls `self._log_panel.log_link(f"New version available: {version} — Download", url)`.

### Menu wiring

Wherever the Help menu currently lives, add a `Preferences...` action that opens `PreferencesDialog`. If there is no Help menu today, create one.

## Data flow

```
1. App starts
2. observability._get_version() → "0.15.1" (or "unknown" on dev)
3. QSettings → user opted in (default True)
4. UpdateChecker.check() fires GET request
5. QNetworkAccessManager reply arrives async
6. UpdateChecker parses tag_name, html_url
7. Version.parse(remote) > Version.parse(current) → emit
8. MainWindow handler logs link with text + URL
9. User sees row in log panel; clicks → browser opens releases page
```

## Error handling

| Failure | Behavior |
|---|---|
| Network unreachable / DNS fail | `logger.debug("Update check network error: %s", e)` ; no UI |
| HTTP 4xx / 5xx | `logger.debug("Update check HTTP %d", status)` ; no UI |
| JSON missing `tag_name` or `html_url` | `logger.debug("Unexpected /latest payload")` ; no UI |
| `packaging.Version` parse error (e.g., tag is `nightly`) | `logger.debug("Version parse failed: %r", tag)` ; no UI |
| Remote version equal or older | Silent; no log entry |
| User disabled in Preferences | Skip `check()` entirely |
| Dev build (`VERSION == "unknown"`) | Skip `check()` entirely |

The principle: the only visible side effect of the check is a single positive log line when there's something to download. Everything else is invisible.

## Testing

### `tests/presentation/services/test_update_checker.py` (new)

- Patch `QNetworkAccessManager` so no real network. Construct a fake `QNetworkReply` (or a `MagicMock` that emits `finished`) with controllable status code + body.
- Case: remote `v0.16.0` > current `0.15.1` → `update_available` emits with `("v0.16.0", "https://github.com/.../releases/tag/v0.16.0")`.
- Case: remote equal to current → no emit.
- Case: remote older than current → no emit.
- Case: HTTP 403 → no emit, `logger.debug` called.
- Case: empty body / malformed JSON → no emit.
- Case: tag is `nightly-20240101` (un-parseable) → no emit, debug log.

### `tests/presentation/dialogs/test_preferences_dialog.py` (new)

- Open dialog with `QSettings` default → checkbox is checked.
- Toggle checkbox + OK → `QSettings.value("updates/check_on_startup")` returns False.
- Toggle + Cancel → `QSettings` unchanged.

`QSettings` in tests: scope it via `QCoreApplication.setOrganizationName("GitCrispTest")` in a fixture so we don't pollute the real user settings. Or use `QSettings(QSettings.IniFormat, QSettings.UserScope, "GitCrispTest", "Test")` directly with a `tmp_path` redirect via `QSettings.setPath`.

### `tests/presentation/widgets/test_log_panel_link.py` (new)

- Adding a link row produces a clickable widget.
- The URL is escaped (`&` becomes `&amp;` etc.) — i.e., a malicious-looking URL doesn't break the HTML.

### Main-window integration test (extend existing main-window tests, no new file)

- On startup with `VERSION == "unknown"`, `UpdateChecker` is not constructed.
- On startup with check disabled via `QSettings`, `UpdateChecker` is not constructed.

## Dependencies

- `packaging` — for `Version` comparison. Add explicitly to `[project] dependencies` in `pyproject.toml`. It is already a transitive dep, but explicit ownership is cleaner.
- `QtNetwork` — part of PySide6, no new top-level dep.

## Open implementation choices (decide during plan-writing, not blocking design)

- Where exactly to wire menu/menu bar: search for the existing `menuBar()` calls and add the Preferences action adjacent. If the codebase has no Help menu, create one.
- Whether to use `QtNetwork` or `urllib` + `QThread`. `QtNetwork` is more idiomatic and avoids manual thread management.
- The exact module path for `_get_version`: prefer importing from `git_gui.observability` since it already centralizes version resolution.
