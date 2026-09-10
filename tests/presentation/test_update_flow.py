"""Behavioural tests for UpdateFlowMixin.

The mixin pulls its required attribute (``_log_panel``) from the
composite that mixes it in. Tests build a thin stand-in object so the
mixin's methods can be exercised in isolation without spinning up the
full ``MainWindow``.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from git_gui.presentation.main_window.update_flow import UpdateFlowMixin


class _Host(UpdateFlowMixin):
    """Bare composite — just provides the attributes the mixin reads."""

    def __init__(self) -> None:
        self._log_panel = MagicMock()


# ── _start_update_check: frozen build with unknown version ────────────────────


def test_unknown_version_in_frozen_build_logs_warning(monkeypatch, caplog):
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("git_gui.presentation.app_settings.get_check_updates", lambda: True)
    monkeypatch.setattr("git_gui.observability._get_version", lambda: "unknown")

    host = _Host()
    with caplog.at_level(logging.WARNING, logger="git_gui.presentation.main_window.update_flow"):
        host._start_update_check()

    matching = [r for r in caplog.records if "unknown" in r.message and "frozen" in r.message]
    assert matching, "expected a WARNING when _get_version is 'unknown' in a frozen build"
    assert matching[0].levelno == logging.WARNING


def test_unknown_version_in_dev_build_stays_quiet(monkeypatch, caplog):
    # No `sys.frozen` attribute — typical dev run via `uv run python main.py`.
    monkeypatch.delattr("sys.frozen", raising=False)
    monkeypatch.setattr("git_gui.presentation.app_settings.get_check_updates", lambda: True)
    monkeypatch.setattr("git_gui.observability._get_version", lambda: "unknown")

    host = _Host()
    with caplog.at_level(logging.DEBUG, logger="git_gui.presentation.main_window.update_flow"):
        host._start_update_check()

    # Dev builds should remain silent — no log line about the unknown version.
    assert not any("unknown" in r.message for r in caplog.records)


def test_disabled_preference_skips_without_checking_version(monkeypatch):
    monkeypatch.setattr("git_gui.presentation.app_settings.get_check_updates", lambda: False)
    version_calls: list[int] = []

    def _spy_version() -> str:
        version_calls.append(1)
        return "0.18.0"

    monkeypatch.setattr("git_gui.observability._get_version", _spy_version)

    host = _Host()
    host._start_update_check()

    assert version_calls == [], "When the user opts out, the version should not even be queried."


def test_known_version_creates_update_checker(monkeypatch):
    monkeypatch.setattr("git_gui.presentation.app_settings.get_check_updates", lambda: True)
    monkeypatch.setattr("git_gui.observability._get_version", lambda: "0.18.0")

    fake_checker_instance = MagicMock()
    fake_checker_cls = MagicMock(return_value=fake_checker_instance)
    with patch(
        "git_gui.presentation.services.update_checker.UpdateChecker",
        fake_checker_cls,
    ):
        host = _Host()
        host._start_update_check()

    fake_checker_cls.assert_called_once()
    assert fake_checker_cls.call_args.kwargs["current_version"] == "0.18.0"
    fake_checker_instance.check.assert_called_once()


# ── _on_update_available: expands log panel + writes link ─────────────────────


def test_on_update_available_expands_log_panel():
    host = _Host()
    host._on_update_available("v0.19.0", "https://github.com/example/releases/v0.19.0")

    # The log panel is collapsed by default — without expand() the user
    # would never see the notification.
    host._log_panel.expand.assert_called_once()


def test_on_update_available_writes_log_link():
    host = _Host()
    host._on_update_available("v0.19.0", "https://github.com/example/releases/v0.19.0")

    host._log_panel.log_link.assert_called_once_with(
        "New version available: v0.19.0 — Download",
        "https://github.com/example/releases/v0.19.0",
    )


def test_on_update_available_expands_before_logging():
    """Expand must happen before log_link, so the link is visible the moment
    it lands. The other order works too but this captures the intent."""
    host = _Host()
    call_order: list[str] = []
    host._log_panel.expand.side_effect = lambda: call_order.append("expand")
    host._log_panel.log_link.side_effect = lambda *_a, **_kw: call_order.append("log_link")

    host._on_update_available("v0.19.0", "https://example.com/release")

    assert call_order == ["expand", "log_link"]
