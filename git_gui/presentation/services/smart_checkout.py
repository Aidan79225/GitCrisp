"""Smart-checkout: intercept the 'branch is in another worktree' error
and switch to the owning worktree instead of surfacing the error."""
from __future__ import annotations

import re

from PySide6.QtCore import QObject, Signal

_COLLISION_RE = re.compile(
    r"already used by worktree at\s+(.+)$",
    re.IGNORECASE | re.MULTILINE,
)


def _looks_like_worktree_collision(err: Exception) -> bool:
    msg = str(err)
    return bool(_COLLISION_RE.search(msg))


class SmartCheckout(QObject):
    """Wraps the bus's `Checkout` command. On worktree-collision errors,
    looks up the owning worktree via `FindWorktreeForBranch` and emits
    `switch_to_worktree_requested(path)`. On all other errors, re-raises.
    """

    switch_to_worktree_requested = Signal(str)  # absolute path

    def __init__(self, checkout, finder, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._checkout = checkout
        self._finder = finder

    def execute(self, branch: str) -> None:
        try:
            self._checkout.execute(branch)
        except Exception as e:
            if not _looks_like_worktree_collision(e):
                raise
            wt = self._finder.execute(branch)
            if wt is None:
                raise
            self.switch_to_worktree_requested.emit(str(wt.path))
