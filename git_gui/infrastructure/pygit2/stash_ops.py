from __future__ import annotations
from datetime import datetime, timezone
import logging

import pygit2

from git_gui.domain.entities import Stash

logger = logging.getLogger(__name__)


class StashOps:
    """Stash-related operations for Pygit2Repository.

    Mixin — not instantiable on its own. Relies on `self._repo` set up
    by the composite class.
    """
    _repo: pygit2.Repository  # provided by the composite

    # ── METHODS COPIED VERBATIM from Pygit2Repository ─────────────────
    def get_stashes(self) -> list[Stash]:
        result = []
        for i, stash in enumerate(self._repo.listall_stashes()):
            ts: datetime | None = None
            try:
                commit = self._repo.get(stash.commit_id)
                if commit is not None:
                    ts = datetime.fromtimestamp(commit.commit_time, tz=timezone.utc)
            except Exception as e:
                logger.warning("Failed to read stash %d timestamp: %s", i, e)
            result.append(Stash(
                index=i,
                message=stash.message,
                oid=str(stash.commit_id),
                timestamp=ts,
            ))
        return result

    def stash(self, message: str) -> None:
        sig = self._get_signature()
        self._repo.stash(sig, message=message, include_untracked=True)

    def pop_stash(self, index: int) -> None:
        self._repo.stash_pop(index=index)

    def apply_stash(self, index: int) -> None:
        self._repo.stash_apply(index=index)

    def drop_stash(self, index: int) -> None:
        self._repo.stash_drop(index=index)
