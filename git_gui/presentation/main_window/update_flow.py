# git_gui/presentation/main_window/update_flow.py
from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)


class UpdateFlowMixin:
    """Background update-check wiring.

    Mixin -- not instantiable on its own. Relies on composite-provided
    attributes (``_log_panel``) set up by ``MainWindow.__init__``.
    """

    def _start_update_check(self) -> None:
        """Kick off the GitHub release check if the user hasn't opted out.

        Skipped for dev builds (no baked version) so local ``uv run`` runs
        don't surface phantom updates against the running checkout.

        In a *frozen* (PyInstaller) build, ``_get_version() == "unknown"``
        means the build-time version bake failed to reach the runtime — log
        a WARNING so the failure is visible in ``~/.gitcrisp/logs/`` instead
        of silently breaking the auto-updater.
        """
        from git_gui.observability import _get_version
        from git_gui.presentation.app_settings import get_check_updates
        from git_gui.presentation.services.update_checker import UpdateChecker

        if not get_check_updates():
            return
        current = _get_version()
        if current == "unknown":
            if getattr(sys, "frozen", False):
                logger.warning(
                    "Update check skipped: _get_version() returned 'unknown' "
                    "in a frozen build. Likely cause: git_gui._build_config "
                    "missing from the PyInstaller bundle (see GitCrisp.spec "
                    "hiddenimports)."
                )
            return
        self._update_checker = UpdateChecker(current_version=current, parent=self)  # type: ignore[arg-type]
        self._update_checker.update_available.connect(self._on_update_available)
        self._update_checker.check()

    def _on_update_available(self, version: str, url: str) -> None:
        # Expand the operations-log panel so the notification is actually
        # visible — it is collapsed and hidden by default, so logging a link
        # into it without expanding means the user never sees the message.
        self._log_panel.expand()  # type: ignore[attr-defined]
        self._log_panel.log_link(f"New version available: {version} — Download", url)  # type: ignore[attr-defined]
