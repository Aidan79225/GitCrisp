"""Which remote a remote-tracking branch is on, for the menus that act on it.

The sidebar and the commit list both emit remote_branch_delete_requested.
They take their split from here so that neither guesses a remote the other
refuses to guess.
"""

from __future__ import annotations

import logging

from git_gui.domain.entities import split_remote_branch
from git_gui.presentation.bus import QueryBus

logger = logging.getLogger(__name__)

REMOTES_UNKNOWN = (
    "The remotes did not load, so which one holds this branch is unknown. "
    "Fix the remote configuration (git remote -v), then try again."
)


def listed_remotes(queries: QueryBus) -> list[str] | None:
    """The repo's remotes, or None when they cannot be listed.

    One remote with an invalid name or refspec in .git/config fails the
    whole listing. Raising from a menu left the right-click doing nothing.
    """
    try:
        return [r.name for r in queries.list_remotes.execute()]
    except Exception as e:
        logger.warning("Listing remotes failed: %s", e)
        return None


def split_if_unambiguous(name: str, remotes: list[str] | None) -> tuple[str, str] | None:
    """`name` as (remote, branch), or None when its remote cannot be known.

    A remote's name may hold a '/', so 'team/upstream/feature' is on 'team' or
    on 'team/upstream' depending on which remotes exist. While they cannot be
    listed (None), only a name with a single '/' has one answer: guessing for
    the others could delete another remote's branch, and the confirmation,
    which joins the parts back together, cannot show the wrong split.
    """
    if remotes is None and name.count("/") > 1:
        return None
    return split_remote_branch(name, remotes or ())
