"""Tests for AvatarLoader: email extraction, hashing, two-tier cache, async fetch."""

from __future__ import annotations

import hashlib

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QImage
from PySide6.QtNetwork import QNetworkReply

from git_gui.presentation.widgets.avatar_loader import (
    AvatarLoader,
    email_from_author,
    gravatar_url,
    md5_email,
)


# ── Pure helpers ────────────────────────────────────────────────────────────
class TestEmailFromAuthor:
    def test_name_with_email(self):
        assert email_from_author("Alice Wang <alice@example.com>") == "alice@example.com"

    def test_email_only_in_brackets(self):
        assert email_from_author("<bob@example.com>") == "bob@example.com"

    def test_bare_email(self):
        assert email_from_author("alice@example.com") == "alice@example.com"

    def test_lowercases(self):
        assert email_from_author("Alice <ALICE@EXAMPLE.COM>") == "alice@example.com"

    def test_strips_whitespace(self):
        assert email_from_author("Alice <  alice@example.com  >") == "alice@example.com"

    def test_no_email(self):
        assert email_from_author("Alice Wang") is None

    def test_empty(self):
        assert email_from_author("") is None


class TestMd5Email:
    def test_matches_gravatar_spec(self):
        # Gravatar spec: lowercased + trimmed email → md5
        expected = hashlib.md5(b"alice@example.com").hexdigest()
        assert md5_email("Alice@Example.com") == expected

    def test_strips_whitespace(self):
        expected = hashlib.md5(b"alice@example.com").hexdigest()
        assert md5_email("  alice@example.com  ") == expected


class TestGravatarUrl:
    def test_default_size(self):
        url = gravatar_url("abc123")
        assert "gravatar.com/avatar/abc123" in url
        assert "d=404" in url

    def test_custom_size(self):
        assert "s=64" in gravatar_url("abc", size=64)


# ── Loader ──────────────────────────────────────────────────────────────────
def _make_png_bytes() -> bytes:
    """Generate a tiny valid PNG via QImage."""
    img = QImage(4, 4, QImage.Format_ARGB32)
    img.fill(0xFF112233)
    from PySide6.QtCore import QBuffer, QIODevice

    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


class TestAvatarLoaderHashHelper:
    def test_hash_for_author(self, tmp_path):
        loader = AvatarLoader(cache_dir=tmp_path, fetcher=lambda h, cb: None)
        assert loader.hash_for_author("Alice <alice@example.com>") == md5_email("alice@example.com")

    def test_hash_for_author_no_email(self, tmp_path):
        loader = AvatarLoader(cache_dir=tmp_path, fetcher=lambda h, cb: None)
        assert loader.hash_for_author("Alice Wang") is None


class TestAvatarLoaderCache:
    def test_no_email_returns_none_no_fetch(self, tmp_path):
        calls = []
        loader = AvatarLoader(cache_dir=tmp_path, fetcher=lambda h, cb: calls.append(h))
        assert loader.get_pixmap("Alice Wang") is None
        assert calls == []

    def test_cache_miss_triggers_fetch(self, tmp_path):
        calls = []
        loader = AvatarLoader(
            cache_dir=tmp_path,
            fetcher=lambda h, cb: calls.append((h, cb)),
        )
        assert loader.get_pixmap("Alice <alice@example.com>") is None
        assert len(calls) == 1
        assert calls[0][0] == md5_email("alice@example.com")

    def test_inflight_dedup(self, tmp_path):
        calls = []
        loader = AvatarLoader(
            cache_dir=tmp_path,
            fetcher=lambda h, cb: calls.append(h),  # don't call cb → still inflight
        )
        loader.get_pixmap("Alice <alice@example.com>")
        loader.get_pixmap("Alice <alice@example.com>")
        assert len(calls) == 1

    def test_successful_fetch_caches_in_memory_and_disk(self, tmp_path, qtbot):
        png_bytes = _make_png_bytes()
        captured_cb = {}

        def fetcher(h, cb):
            captured_cb["cb"] = cb
            captured_cb["h"] = h

        loader = AvatarLoader(cache_dir=tmp_path, fetcher=fetcher)
        with qtbot.waitSignal(loader.avatar_ready, timeout=1000):
            loader.get_pixmap("Alice <alice@example.com>")
            captured_cb["cb"](png_bytes)

        h = md5_email("alice@example.com")
        assert (tmp_path / f"{h}.png").exists()
        # Subsequent call returns memory-cached pixmap, no new fetch
        calls_before = list(captured_cb)
        pix = loader.get_pixmap("Alice <alice@example.com>")
        assert pix is not None and not pix.isNull()

    def test_404_caches_miss_marker(self, tmp_path, qtbot):
        captured = {}

        def fetcher(h, cb):
            captured["cb"] = cb

        loader = AvatarLoader(cache_dir=tmp_path, fetcher=fetcher)
        with qtbot.waitSignal(loader.avatar_ready, timeout=1000):
            loader.get_pixmap("Bob <bob@example.com>")
            captured["cb"](None)  # simulate 404

        h = md5_email("bob@example.com")
        assert (tmp_path / f"{h}.404").exists()
        assert (tmp_path / f"{h}.png").exists() is False
        # Subsequent call returns None, no new fetch
        loader2_calls = []
        loader._fetcher = lambda h, cb: loader2_calls.append(h)
        assert loader.get_pixmap("Bob <bob@example.com>") is None
        assert loader2_calls == []

    def test_disk_cache_hit_on_fresh_loader(self, tmp_path):
        # Pre-populate disk cache
        png_bytes = _make_png_bytes()
        h = md5_email("carol@example.com")
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / f"{h}.png").write_bytes(png_bytes)

        calls = []
        loader = AvatarLoader(cache_dir=tmp_path, fetcher=lambda h, cb: calls.append(h))
        pix = loader.get_pixmap("Carol <carol@example.com>")
        assert pix is not None
        assert not pix.isNull()
        assert calls == []  # no fetch needed

    def test_disk_404_marker_hit_on_fresh_loader(self, tmp_path):
        h = md5_email("dave@example.com")
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / f"{h}.404").touch()

        calls = []
        loader = AvatarLoader(cache_dir=tmp_path, fetcher=lambda h, cb: calls.append(h))
        assert loader.get_pixmap("Dave <dave@example.com>") is None
        assert calls == []


class TestAvatarLoaderEnabled:
    def test_default_enabled(self, tmp_path):
        loader = AvatarLoader(cache_dir=tmp_path, fetcher=lambda h, cb: None)
        assert loader.is_enabled() is True

    def test_disabled_returns_none_no_fetch(self, tmp_path):
        calls = []
        loader = AvatarLoader(
            cache_dir=tmp_path,
            fetcher=lambda h, cb: calls.append(h),
            enabled=False,
        )
        assert loader.get_pixmap("Alice <alice@example.com>") is None
        assert calls == []

    def test_set_enabled_emits_signal(self, tmp_path, qtbot):
        loader = AvatarLoader(cache_dir=tmp_path, fetcher=lambda h, cb: None)
        with qtbot.waitSignal(loader.enabled_changed, timeout=1000) as blocker:
            loader.set_enabled(False)
        assert blocker.args == [False]
        assert loader.is_enabled() is False

    def test_set_enabled_idempotent_no_signal(self, tmp_path, qtbot):
        loader = AvatarLoader(cache_dir=tmp_path, fetcher=lambda h, cb: None)
        # already enabled; setting True again should not emit
        with qtbot.assertNotEmitted(loader.enabled_changed):
            loader.set_enabled(True)

    def test_re_enable_uses_cached_pixmap(self, tmp_path, qtbot):
        # Pre-populate disk cache so we can verify re-enable serves it
        # without a network call.
        png_bytes = _make_png_bytes()
        h = md5_email("frank@example.com")
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / f"{h}.png").write_bytes(png_bytes)

        calls = []
        loader = AvatarLoader(
            cache_dir=tmp_path,
            fetcher=lambda h, cb: calls.append(h),
            enabled=False,
        )
        assert loader.get_pixmap("Frank <frank@example.com>") is None
        loader.set_enabled(True)
        pix = loader.get_pixmap("Frank <frank@example.com>")
        assert pix is not None and not pix.isNull()
        assert calls == []  # disk hit, no network


class TestAvatarLoaderSignal:
    def test_signal_carries_email_hash(self, tmp_path, qtbot):
        png_bytes = _make_png_bytes()
        captured = {}

        def fetcher(h, cb):
            captured["cb"] = cb

        loader = AvatarLoader(cache_dir=tmp_path, fetcher=fetcher)
        with qtbot.waitSignal(loader.avatar_ready, timeout=1000) as blocker:
            loader.get_pixmap("Eve <eve@example.com>")
            captured["cb"](png_bytes)
        assert blocker.args == [md5_email("eve@example.com")]


# ── Gravatar's HTTP replies ─────────────────────────────────────────────────
class _Reply:
    """The parts of a QNetworkReply that AvatarLoader reads."""

    def __init__(self, error, status, body: bytes = b"") -> None:
        self._error = error
        self._status = status
        self._body = body

    def error(self):
        return self._error

    def attribute(self, _attribute):
        return self._status

    def readAll(self) -> QByteArray:
        return QByteArray(self._body)

    def deleteLater(self) -> None:
        pass


_BOB = "Bob <bob@example.com>"
_BOB_HASH = md5_email("bob@example.com")


def _answer_fetch(cache_dir, reply: _Reply) -> list[str]:
    """Look Bob up, answer the fetch with *reply*; return the fetches started."""
    fetched: list[str] = []
    loader = AvatarLoader(cache_dir=cache_dir, fetcher=lambda h, cb: fetched.append(h))
    loader.get_pixmap(_BOB)
    loader._on_reply(_BOB_HASH, reply)
    loader.get_pixmap(_BOB)
    return fetched


def _fetches_after_restart(cache_dir) -> list[str]:
    fetched: list[str] = []
    loader = AvatarLoader(cache_dir=cache_dir, fetcher=lambda h, cb: fetched.append(h))
    loader.get_pixmap(_BOB)
    return fetched


class TestAvatarLoaderHttpReplies:
    def test_a_404_is_remembered_across_restarts(self, tmp_path):
        _answer_fetch(tmp_path, _Reply(QNetworkReply.ContentNotFoundError, 404))

        assert (tmp_path / f"{_BOB_HASH}.404").exists()
        assert _fetches_after_restart(tmp_path) == []

    def test_being_offline_is_not_remembered_as_no_avatar(self, tmp_path):
        _answer_fetch(tmp_path, _Reply(QNetworkReply.HostNotFoundError, None))

        assert not (tmp_path / f"{_BOB_HASH}.404").exists()
        assert _fetches_after_restart(tmp_path) == [_BOB_HASH]

    def test_a_server_error_is_not_remembered_as_no_avatar(self, tmp_path):
        _answer_fetch(tmp_path, _Reply(QNetworkReply.InternalServerError, 503))

        assert _fetches_after_restart(tmp_path) == [_BOB_HASH]

    def test_a_page_that_is_not_an_image_is_not_remembered_as_no_avatar(self, tmp_path):
        """A captive portal answers 200 with its own sign-in page."""
        _answer_fetch(tmp_path, _Reply(QNetworkReply.NoError, 200, b"<html>Sign in</html>"))

        assert _fetches_after_restart(tmp_path) == [_BOB_HASH]

    def test_a_failed_fetch_is_not_retried_on_every_paint(self, tmp_path):
        fetched = _answer_fetch(tmp_path, _Reply(QNetworkReply.HostNotFoundError, None))

        assert fetched == [_BOB_HASH]


class TestAvatarLoaderUnwritableCache:
    """The cache directory cannot be created: a file sits at its path."""

    def test_a_fetched_avatar_is_still_shown(self, tmp_path, qtbot):
        blocked = tmp_path / "avatars"
        blocked.write_text("")
        answers = []
        loader = AvatarLoader(cache_dir=blocked, fetcher=lambda h, cb: answers.append(cb))
        loader.get_pixmap(_BOB)

        with qtbot.waitSignal(loader.avatar_ready, timeout=1000):
            answers[0](_make_png_bytes())

        pix = loader.get_pixmap(_BOB)
        assert pix is not None and not pix.isNull()
