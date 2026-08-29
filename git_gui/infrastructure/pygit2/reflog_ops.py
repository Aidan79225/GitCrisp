# git_gui/infrastructure/pygit2/reflog_ops.py
from __future__ import annotations

from datetime import datetime

import pygit2

from git_gui.domain.entities import ReflogEntry

# A reflog message is "<operation>: <summary>", where the operation may carry a
# qualifier of its own — "commit (amend)", "rebase (finish)". The qualifier is
# the part that says what actually happened, so it is kept with the operation
# rather than split off into the summary.
_SEPARATOR = ": "


_NULL_OID = "0" * 40


def _split_message(message: str | None) -> tuple[str, str]:
    if not message:
        # The entry that creates a ref carries no message at all.
        return "", ""
    operation, found, summary = message.partition(_SEPARATOR)
    if not found:
        # Not every writer follows the convention; keep the text rather than
        # dropping it into an operation column it does not belong in.
        return "", message.strip()
    return operation.strip(), summary.strip()


class ReflogOps:
    """Reads of a ref's reflog — the record that makes undo possible.

    Mixin — not instantiable on its own. Relies on `self._repo` set up by the
    composite class.
    """

    _repo: pygit2.Repository  # provided by the composite

    def get_reflog(self, ref: str = "HEAD", limit: int = 100) -> list[ReflogEntry]:
        """Recent movements of `ref`, newest first.

        Defaults to HEAD rather than the current branch: HEAD's reflog also
        records checkouts between branches, so it is the complete account of
        where the working copy has been — which is what someone looking for a
        state to get back to needs.
        """
        reference = self._repo.references.get(ref)
        if reference is None:
            raise ValueError(f"No such ref: {ref}")

        entries: list[ReflogEntry] = []
        for index, entry in enumerate(reference.log()):
            if index >= limit:
                break
            operation, summary = _split_message(entry.message)
            entries.append(
                ReflogEntry(
                    index=index,
                    oid_new=str(entry.oid_new),
                    # The null oid means the ref did not exist before this
                    # entry, so there is no earlier state to go back to. Saying
                    # that with None keeps callers from offering to restore it.
                    oid_old=None if str(entry.oid_old) == _NULL_OID else str(entry.oid_old),
                    operation=operation,
                    summary=summary,
                    committer=entry.committer.name or "",
                    timestamp=datetime.fromtimestamp(entry.committer.time),
                )
            )
        return entries
