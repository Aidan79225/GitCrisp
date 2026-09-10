"""GitHub release-check service.

Two layers:

- `fetch_latest_release`: pure sync function. Easy to test by patching
  `urllib.request.urlopen`. Returns ``(tag, html_url)`` or ``None`` for
  any failure (network, HTTP, JSON, missing fields).
- `UpdateChecker`: a QObject that runs ``fetch_latest_release`` on a
  ``threading.Thread`` and emits ``update_available(version, url)``
  when the remote version is newer than the running one. We use a
  Python thread rather than ``QThread`` because Qt signals are already
  thread-safe (cross-thread emits auto-queue to the receiver's thread)
  and QThread's moveToThread+deleteLater lifecycle is fragile in test
  harnesses on Linux — it has segfaulted in pytest-qt CI runs.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.request

from packaging.version import InvalidVersion, Version
from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)

LATEST_RELEASE_URL = "https://api.github.com/repos/Aidan79225/GitCrisp/releases/latest"
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


class UpdateChecker(QObject):
    """Background GitHub release check. Emits when a newer release is found.

    ``check()`` spawns a daemon ``threading.Thread`` that runs
    ``fetch_latest_release`` and hands the result back via the private
    ``_result_ready`` signal. Qt routes that signal to ``_on_finished``
    on the receiver's thread (the main GUI thread), so all version
    parsing and the public ``update_available`` emit happen there.
    """

    update_available = Signal(str, str)  # (version_tag, html_url)
    _result_ready = Signal(object)  # tuple[str, str] | None — internal

    def __init__(
        self,
        current_version: str,
        url: str = LATEST_RELEASE_URL,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._current_version = current_version
        self._url = url
        self._result_ready.connect(self._on_finished)

    def check(self) -> None:
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

    def _run(self) -> None:
        # Runs on the background thread. The signal emit is auto-queued
        # to the main thread by Qt.
        self._result_ready.emit(fetch_latest_release(self._url))

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
