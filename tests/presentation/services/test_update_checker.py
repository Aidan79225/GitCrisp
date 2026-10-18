"""Tests for fetch_latest_release.

The function is sync and pure — mock urllib.request.urlopen with a
context manager whose .read() returns bytes.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest

from git_gui.presentation.services.update_checker import UpdateChecker, fetch_latest_release


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


_FETCH = "git_gui.presentation.services.update_checker.fetch_latest_release"


def test_update_checker_emits_when_remote_is_newer(qtbot):
    checker = UpdateChecker(current_version="0.15.1")
    fake_result = ("v0.16.0", "https://github.com/.../releases/tag/v0.16.0")
    with patch(_FETCH, return_value=fake_result):
        with qtbot.waitSignal(checker.update_available, timeout=2000) as blocker:
            checker.check()
    assert blocker.args == ["v0.16.0", "https://github.com/.../releases/tag/v0.16.0"]


@pytest.mark.parametrize(
    ("current_version", "fetch_result"),
    [
        pytest.param("0.16.0", ("v0.16.0", "https://..."), id="remote-equal"),
        pytest.param("0.16.0", ("v0.15.1", "https://..."), id="remote-older"),
        pytest.param("0.15.1", None, id="fetch-failed"),
        pytest.param("0.15.1", ("nightly-foo", "https://..."), id="remote-tag-unparseable"),
    ],
)
def test_update_checker_stays_silent(qtbot, current_version, fetch_result):
    checker = UpdateChecker(current_version=current_version)
    received: list[tuple] = []
    checker.update_available.connect(lambda *a: received.append(a))
    with patch(_FETCH, return_value=fetch_result):
        # _on_finished was connected first, so it has run once this arrives.
        with qtbot.waitSignal(checker._result_ready, timeout=2000):
            checker.check()
    assert received == []
