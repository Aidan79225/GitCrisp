"""Crash reporting via Sentry (opt-in).

DSN resolution order:
1. ``git_gui._build_config.DSN`` — baked in at release build time so
   distributed binaries report crashes without the user touching anything.
2. ``GITCRISP_SENTRY_DSN`` env var — for local dev or self-built runs.

Sentry stays disabled when neither source provides a value, so local
dev never ships events by accident. Performance/profile sampling is
forced to zero — the free tier's quota is 5k errors/month and the
desktop population doesn't need transaction tracing.

``before_send`` redacts the user's HOME path from exception messages
and breadcrumbs, since repo paths frequently contain real names.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


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


def _redact_home(text: str, home: str) -> str:
    if not text:
        return text
    return text.replace(home, "~")


def _before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    home = str(Path.home())
    for exc in event.get("exception", {}).get("values", []):
        if "value" in exc and isinstance(exc["value"], str):
            exc["value"] = _redact_home(exc["value"], home)
    for crumb in event.get("breadcrumbs", {}).get("values", []) or []:
        if isinstance(crumb.get("message"), str):
            crumb["message"] = _redact_home(crumb["message"], home)
    return event


def init_crash_reporting() -> bool:
    """Initialize Sentry if a DSN is available (baked or env var).

    Returns True if Sentry was initialized, False otherwise.
    Safe to call multiple times — the SDK itself is idempotent.
    """
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
        before_send=_before_send,
    )
    logger.info("Crash reporting initialized")
    return True
