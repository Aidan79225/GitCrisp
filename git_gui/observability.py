"""Crash reporting via Sentry (opt-in).

DSN resolution order:
1. ``git_gui._build_config.DSN`` — baked in at release build time so
   distributed binaries report crashes without the user touching anything.
2. ``GITCRISP_SENTRY_DSN`` env var — for local dev or self-built runs.

Sentry stays disabled when neither source provides a value, so local
dev never ships events by accident. Performance/profile sampling is
forced to zero — the free tier's quota is 5k errors/month and the
desktop population doesn't need transaction tracing.

Reports carry no local variables and no hostname, and ``before_send``
redacts the user's HOME path from every string in the event, since repo
paths frequently contain real names.

Users can turn reporting off in Preferences. Off at startup, Sentry is never
initialized; switched off mid-session, ``before_send`` drops every event
from then on, since the SDK cannot be cleanly torn down.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_enabled = True
_initialized = False


def _get_baked_config() -> tuple[str | None, str | None]:
    """Read DSN + version from a build-time-generated module if present."""
    try:
        from git_gui import _build_config  # type: ignore[attr-defined]
    except ImportError:
        return None, None
    return (
        getattr(_build_config, "DSN", None) or None,
        getattr(_build_config, "VERSION", None) or None,
    )


def _get_dsn() -> str | None:
    baked, _ = _get_baked_config()
    return baked or os.environ.get("GITCRISP_SENTRY_DSN")


def _get_version() -> str:
    _, baked_version = _get_baked_config()
    if baked_version:
        return baked_version
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("gitcrisp")
    except PackageNotFoundError:
        return os.environ.get("GITCRISP_VERSION", "unknown")


def _home_pattern(home: str) -> re.Pattern[str]:
    """Match *home* however an event spells it.

    One Windows home reaches an event with backslashes, with forward slashes
    (libgit2 messages), and with doubled backslashes (a path inside a repr);
    and since Windows and macOS file systems ignore case, so does the match.
    """
    separator = r"[\\/]+"
    return re.compile(separator.join(map(re.escape, re.split(separator, home))), re.IGNORECASE)


def _redact_home(value: Any, home: re.Pattern[str]) -> Any:
    if isinstance(value, str):
        return home.sub("~", value)
    if isinstance(value, dict):
        return {key: _redact_home(item, home) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_home(item, home) for item in value]
    return value


def _before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """Drop the event if reporting is off; otherwise redact the home path.

    Every string is redacted rather than a list of known fields: the path
    turns up in messages, frame paths, log arguments and ``sys.argv``, and a
    field missed here is a field that leaks.
    """
    if not _enabled:
        return None
    return _redact_home(event, _home_pattern(str(Path.home())))


def init_crash_reporting(enabled: bool = True) -> bool:
    """Initialize Sentry if the user allows it and a DSN is available.

    ``enabled`` is the user's preference; this module stays free of Qt, so
    the caller reads it. Returns True if Sentry was initialized, False
    otherwise. Safe to call multiple times — the SDK itself is idempotent.
    """
    global _enabled, _initialized
    _enabled = enabled
    if not enabled:
        logger.info("Crash reporting turned off in preferences")
        return False
    dsn = _get_dsn()
    if not dsn:
        logger.debug("No Sentry DSN available; crash reporting disabled")
        return False
    try:
        import sentry_sdk
    except ImportError:
        logger.warning("sentry-sdk not installed; crash reporting disabled")
        return False

    sentry_sdk.init(
        dsn=dsn,
        release=f"gitcrisp@{_get_version()}",
        environment=os.environ.get("GITCRISP_ENV", "production"),
        traces_sample_rate=0.0,
        profiles_sample_rate=0.0,
        send_default_pii=False,
        # Locals hold repository paths and the text of the user's files, and
        # the SDK's default server name is the machine's hostname.
        include_local_variables=False,
        server_name="",
        before_send=_before_send,
    )
    _initialized = True
    logger.info("Crash reporting initialized")
    return True


def set_crash_reporting_enabled(enabled: bool) -> None:
    """Apply a preference change to the running app.

    Turning reporting on starts Sentry if it was never started; turning it
    off makes ``before_send`` drop every event from now on.
    """
    global _enabled
    if enabled and not _initialized:
        init_crash_reporting(enabled=True)
    _enabled = enabled
