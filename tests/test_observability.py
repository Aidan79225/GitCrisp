from __future__ import annotations

import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from git_gui.observability import _before_send, init_crash_reporting


def test_init_returns_false_when_dsn_missing(monkeypatch):
    monkeypatch.delenv("GITCRISP_SENTRY_DSN", raising=False)
    monkeypatch.setattr("git_gui.observability._get_baked_config", lambda: (None, None))
    assert init_crash_reporting() is False


def test_init_calls_sentry_when_dsn_set(monkeypatch):
    monkeypatch.setenv("GITCRISP_SENTRY_DSN", "https://key@example.ingest.sentry.io/123")
    monkeypatch.setattr("git_gui.observability._get_baked_config", lambda: (None, None))
    fake_sentry = MagicMock()
    with patch.dict("sys.modules", {"sentry_sdk": fake_sentry}):
        assert init_crash_reporting() is True
    fake_sentry.init.assert_called_once()
    kwargs = fake_sentry.init.call_args.kwargs
    assert kwargs["dsn"] == "https://key@example.ingest.sentry.io/123"
    assert kwargs["traces_sample_rate"] == 0.0
    assert kwargs["profiles_sample_rate"] == 0.0
    assert kwargs["send_default_pii"] is False
    assert kwargs["release"].startswith("gitcrisp@")


def test_baked_dsn_overrides_env(monkeypatch):
    """Built binaries with a baked _build_config should ignore the env var."""
    monkeypatch.setenv("GITCRISP_SENTRY_DSN", "https://env@example.ingest.sentry.io/1")
    monkeypatch.setattr(
        "git_gui.observability._get_baked_config",
        lambda: ("https://baked@example.ingest.sentry.io/2", "1.2.3"),
    )
    fake_sentry = MagicMock()
    with patch.dict("sys.modules", {"sentry_sdk": fake_sentry}):
        assert init_crash_reporting() is True
    kwargs = fake_sentry.init.call_args.kwargs
    assert kwargs["dsn"] == "https://baked@example.ingest.sentry.io/2"
    assert kwargs["release"] == "gitcrisp@1.2.3"


def test_baked_config_with_empty_dsn_falls_back_to_env(monkeypatch):
    """An empty DSN string in _build_config (template never substituted) falls back."""
    monkeypatch.setenv("GITCRISP_SENTRY_DSN", "https://env@example.ingest.sentry.io/1")
    monkeypatch.setattr("git_gui.observability._get_baked_config", lambda: (None, None))
    fake_sentry = MagicMock()
    with patch.dict("sys.modules", {"sentry_sdk": fake_sentry}):
        assert init_crash_reporting() is True
    kwargs = fake_sentry.init.call_args.kwargs
    assert kwargs["dsn"] == "https://env@example.ingest.sentry.io/1"


def test_before_send_redacts_home_in_exception_value():
    home = str(Path.home())
    event = {
        "exception": {
            "values": [
                {"type": "FileNotFoundError", "value": f"No such file: {home}/secret/repo"},
            ]
        }
    }
    out = _before_send(event, {})
    assert out is not None
    assert home not in out["exception"]["values"][0]["value"]
    assert "~/secret/repo" in out["exception"]["values"][0]["value"]


def test_before_send_redacts_home_in_breadcrumbs():
    home = str(Path.home())
    event = {
        "breadcrumbs": {
            "values": [{"message": f"opened {home}/work/proj"}],
        }
    }
    out = _before_send(event, {})
    assert out is not None
    assert "~/work/proj" in out["breadcrumbs"]["values"][0]["message"]


# ── User opt-out ─────────────────────────────────────────────────────────────


def test_init_skips_sentry_when_user_opted_out(monkeypatch):
    monkeypatch.setenv("GITCRISP_SENTRY_DSN", "https://key@example.ingest.sentry.io/123")
    fake_sentry = MagicMock()
    with patch.dict("sys.modules", {"sentry_sdk": fake_sentry}):
        assert init_crash_reporting(enabled=False) is False
    fake_sentry.init.assert_not_called()


def test_turning_reporting_off_drops_events():
    from git_gui.observability import set_crash_reporting_enabled

    set_crash_reporting_enabled(False)
    assert _before_send({"exception": {"values": []}}, {}) is None


def test_turning_reporting_on_mid_session_starts_sentry(monkeypatch):
    from git_gui.observability import set_crash_reporting_enabled

    monkeypatch.setenv("GITCRISP_SENTRY_DSN", "https://key@example.ingest.sentry.io/123")
    monkeypatch.setattr("git_gui.observability._get_baked_config", lambda: (None, None))
    fake_sentry = MagicMock()
    with patch.dict("sys.modules", {"sentry_sdk": fake_sentry}):
        init_crash_reporting(enabled=False)
        set_crash_reporting_enabled(True)
        set_crash_reporting_enabled(False)
        set_crash_reporting_enabled(True)
    fake_sentry.init.assert_called_once()
    assert _before_send({"exception": {"values": []}}, {}) is not None


# ── What a report may carry ──────────────────────────────────────────────────


def _strings(value):
    """Every string anywhere in a (serialized) Sentry event."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _mentions_home(event) -> bool:
    home = str(Path.home()).lower()
    spellings = {home, home.replace("\\", "/"), home.replace("\\", "\\\\")}
    return any(spelling in text.lower() for text in _strings(event) for spelling in spellings)


def test_init_keeps_local_variables_and_hostname_out_of_reports(monkeypatch):
    monkeypatch.setenv("GITCRISP_SENTRY_DSN", "https://key@example.ingest.sentry.io/123")
    monkeypatch.setattr("git_gui.observability._get_baked_config", lambda: (None, None))
    fake_sentry = MagicMock()
    with patch.dict("sys.modules", {"sentry_sdk": fake_sentry}):
        init_crash_reporting()
    kwargs = fake_sentry.init.call_args.kwargs
    assert kwargs["include_local_variables"] is False
    assert kwargs["server_name"] is not None
    assert kwargs["server_name"] != socket.gethostname()


def test_before_send_redacts_home_wherever_the_event_carries_it():
    home = str(Path.home())
    posix_home = Path.home().as_posix()
    event = {
        "exception": {
            "values": [
                {
                    "value": f"failed to parse config (in {posix_home}/proj/.git/config:1)",
                    "stacktrace": {
                        "frames": [{"abs_path": f"{home}/app/x.py", "filename": "x.py"}]
                    },
                }
            ]
        },
        "logentry": {
            "message": "Cannot open %s",
            "params": [f"{home}/clients/acme"],
            "formatted": f"Cannot open {home}/clients/acme",
        },
        "extra": {"sys.argv": [f"{home}/Programs/GitCrisp/GitCrisp.exe"]},
        "breadcrumbs": {"values": [{"message": "ok", "data": {"path": f"{posix_home}/w"}}]},
    }
    out = _before_send(event, {})
    assert out is not None
    assert not _mentions_home(out)
    assert out["logentry"]["params"] == ["~/clients/acme"]


def test_before_send_redacts_home_inside_a_repr_with_doubled_backslashes():
    event = {"exception": {"values": [{"value": f"No such file: {str(Path.home())!r}"}]}}
    out = _before_send(event, {})
    assert out is not None
    assert not _mentions_home(out)


def test_before_send_redacts_home_whatever_its_case():
    event = {"exception": {"values": [{"value": f"open {str(Path.home()).upper()}/x"}]}}
    out = _before_send(event, {})
    assert out is not None
    assert out["exception"]["values"][0]["value"] == "open ~/x"


@pytest.fixture
def captured_events(monkeypatch):
    """Run the real SDK with this module's options, keeping what it would send.

    Default integrations stay off so the SDK installs no process-wide hooks
    that would outlive the test.
    """
    import sentry_sdk
    from sentry_sdk.transport import Transport

    events: list[dict] = []

    class _Capturing(Transport):
        def capture_envelope(self, envelope):
            event = envelope.get_event()
            if event is not None:
                events.append(event)

    real_init = sentry_sdk.init

    def _init(**kwargs):
        return real_init(**kwargs, transport=_Capturing(), default_integrations=False)

    monkeypatch.setattr(sentry_sdk, "init", _init)
    monkeypatch.setenv("GITCRISP_SENTRY_DSN", "https://key@example.ingest.sentry.io/123")
    monkeypatch.setattr("git_gui.observability._get_baked_config", lambda: (None, None))
    monkeypatch.setattr("git_gui.observability._initialized", False)
    yield events
    sentry_sdk.get_client().close()
    sentry_sdk.get_global_scope().set_client(None)


def test_a_crash_report_carries_no_locals_hostname_or_home_path(captured_events):
    import sentry_sdk

    assert init_crash_reporting() is True
    path = str(Path.home() / "clients" / "acme")
    try:
        raise OSError(f"cannot open {Path(path).as_posix()}")
    except OSError:
        sentry_sdk.capture_exception()

    (event,) = captured_events
    frames = event["exception"]["values"][0]["stacktrace"]["frames"]
    assert all("vars" not in frame for frame in frames)
    assert event.get("server_name") != socket.gethostname()
    assert not _mentions_home(event)
