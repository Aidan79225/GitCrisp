from __future__ import annotations

from git_gui.presentation.bus import CommandBus


class AskedRepoGuardMixin:
    """Keeps an action the user confirmed from running in a different repo.

    A confirmation box runs a nested event loop, and a repo switch that was
    already on its way lands inside it and replaces the window's buses. What
    the user agreed to was about the repo on screen when they were asked.

    Mixin — not instantiable on its own. Relies on composite-provided
    attributes set up by MainWindow's __init__.
    """

    def _repo_switched_while_asking(self, asked_in: CommandBus | None, op_name: str) -> bool:
        """Whether the active repo is no longer *asked_in*, logging *op_name*
        as skipped if so."""
        if self._commands is asked_in:
            return False
        self._log_panel.expand()
        self._log_panel.log_error(
            f"{op_name} — skipped: another repo opened while you were deciding. "
            "Nothing was changed."
        )
        return True
