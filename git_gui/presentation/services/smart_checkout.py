"""Smart-checkout: when the branch is already checked out in another worktree,
switch to that worktree instead of failing to check it out here."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from git_gui.domain.entities import Worktree


class SmartCheckout(QObject):
    """Wraps the bus's `Checkout` command. Before checking out, asks
    `FindWorktreeForBranch` which worktree has the branch; if it is another
    one, emits `switch_to_worktree_requested(path)` instead.

    Asked first rather than read from the checkout's error: pygit2 refuses
    such a checkout only after it has written the branch's files over this
    working tree, and its message is libgit2's, not git's.
    """

    switch_to_worktree_requested = Signal(str)  # absolute path

    def __init__(
        self,
        checkout,
        finder,
        parent: QObject | None = None,
        *,
        current_worktree: str | None = None,
    ) -> None:
        """*current_worktree* is the session's own worktree; None means the main one."""
        super().__init__(parent)
        self._checkout = checkout
        self._finder = finder
        self._current_worktree = current_worktree

    def execute(self, branch: str) -> None:
        owner = self._finder.execute(branch)
        if owner is not None and not self._is_current(owner):
            self.switch_to_worktree_requested.emit(str(owner.path))
            return
        self._checkout.execute(branch)

    def _is_current(self, worktree: Worktree) -> bool:
        if self._current_worktree is None:
            return worktree.is_main
        return Path(worktree.path).resolve() == Path(self._current_worktree).resolve()
