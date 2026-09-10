# git_gui/presentation/widgets/avatar_loader.py
"""Async avatar loader. Resolves an author string to a Gravatar QPixmap.

Two-tier cache:
 - in-memory dict keyed by md5(email)
 - disk under ~/.gitcrisp/avatars/{md5}.{png|404}

A `.404` marker means Gravatar has no image for this email — we don't refetch.
On a hit, `get_pixmap()` returns synchronously. On a miss, it kicks off an
async fetch and emits `avatar_ready(email_hash)` when the pixmap is available.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, QUrl, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

GRAVATAR_SIZE = 128  # request 128px so 36px avatars stay sharp on HiDPI

_EMAIL_RE = re.compile(r"<([^>]+)>")


def email_from_author(author: str) -> str | None:
    """Extract an email from `Name <email>` or return the bare string if it
    looks like an email. Lowercased + stripped. None if nothing usable."""
    if not author:
        return None
    m = _EMAIL_RE.search(author)
    if m:
        candidate = m.group(1)
    elif "@" in author:
        candidate = author
    else:
        return None
    candidate = candidate.strip().lower()
    return candidate or None


def md5_email(email: str) -> str:
    return hashlib.md5(email.strip().lower().encode("utf-8")).hexdigest()


def gravatar_url(email_hash: str, size: int = GRAVATAR_SIZE) -> str:
    return f"https://www.gravatar.com/avatar/{email_hash}?s={size}&d=404"


class AvatarLoader(QObject):
    """Singleton-style loader. Use `get_avatar_loader()` for the default instance."""

    avatar_ready = Signal(str)  # email_hash whose pixmap just became available
    enabled_changed = Signal(bool)  # gravatar feature toggled by the user

    def __init__(
        self,
        cache_dir: Path | None = None,
        fetcher: Callable[[str, Callable[[bytes | None], None]], None] | None = None,
        enabled: bool = True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._cache_dir = cache_dir or Path.home() / ".gitcrisp" / "avatars"
        self._memory: dict[str, QPixmap | None] = {}
        self._inflight: set[str] = set()
        self._enabled = enabled
        # Injectable fetcher for tests; production uses QNetworkAccessManager.
        self._fetcher = fetcher
        self._nam: QNetworkAccessManager | None = None

    # ── Public API ──────────────────────────────────────────────────────────
    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, value: bool) -> None:
        if self._enabled == value:
            return
        self._enabled = value
        self.enabled_changed.emit(value)

    def get_pixmap(self, author: str) -> QPixmap | None:
        """Return a cached pixmap for *author*, or None if unavailable.
        Triggers an async fetch on cache miss; listen on `avatar_ready`.
        Returns None and skips fetching when the loader is disabled."""
        if not self._enabled:
            return None
        email = email_from_author(author)
        if email is None:
            return None
        h = md5_email(email)

        # Memory hit (None means "known to have no avatar")
        if h in self._memory:
            return self._memory[h]

        # Disk hit
        png = self._cache_dir / f"{h}.png"
        miss_marker = self._cache_dir / f"{h}.404"
        if png.exists():
            pix = QPixmap(str(png))
            self._memory[h] = pix if not pix.isNull() else None
            return self._memory[h]
        if miss_marker.exists():
            self._memory[h] = None
            return None

        # Network fetch
        if h not in self._inflight:
            self._inflight.add(h)
            self._start_fetch(h)
        return None

    # ── Internals ───────────────────────────────────────────────────────────
    def _start_fetch(self, email_hash: str) -> None:
        if self._fetcher is not None:
            self._fetcher(email_hash, lambda data: self._on_fetched(email_hash, data))
            return
        if self._nam is None:
            self._nam = QNetworkAccessManager(self)
        req = QNetworkRequest(QUrl(gravatar_url(email_hash)))
        req.setHeader(QNetworkRequest.UserAgentHeader, "GitCrisp/1.0")
        reply = self._nam.get(req)
        reply.finished.connect(lambda r=reply, h=email_hash: self._on_reply(h, r))

    def _on_reply(self, email_hash: str, reply: QNetworkReply) -> None:
        try:
            status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            if reply.error() == QNetworkReply.NoError and status == 200:
                data = bytes(reply.readAll())
                self._on_fetched(email_hash, data)
            else:
                # 404 or any error → cache as miss so we don't retry.
                self._on_fetched(email_hash, None)
        finally:
            reply.deleteLater()

    def _on_fetched(self, email_hash: str, data: bytes | None) -> None:
        self._inflight.discard(email_hash)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        if data:
            pix = QPixmap()
            if pix.loadFromData(QByteArray(data)) and not pix.isNull():
                (self._cache_dir / f"{email_hash}.png").write_bytes(data)
                self._memory[email_hash] = pix
                self.avatar_ready.emit(email_hash)
                return
        # No data or invalid image → mark miss.
        try:
            (self._cache_dir / f"{email_hash}.404").touch()
        except OSError:
            pass
        self._memory[email_hash] = None
        self.avatar_ready.emit(email_hash)

    def hash_for_author(self, author: str) -> str | None:
        email = email_from_author(author)
        return md5_email(email) if email else None


_default_loader: AvatarLoader | None = None


def get_avatar_loader() -> AvatarLoader:
    global _default_loader
    if _default_loader is None:
        # Late import to keep this module independent of the theme package.
        from git_gui.presentation.theme.settings import load_settings

        enabled = bool(load_settings().get("avatar_gravatar_enabled", True))
        _default_loader = AvatarLoader(enabled=enabled)
    return _default_loader
