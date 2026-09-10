"""Tests for fetch_latest_release.

The function is sync and pure — mock urllib.request.urlopen with a
context manager whose .read() returns bytes.
"""

from __future__ import annotations

import json
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


from unittest.mock import patch as _patch


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
