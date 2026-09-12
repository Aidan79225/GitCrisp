from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

WORKING_TREE_OID = "WORKING_TREE"


class StagingState(StrEnum):
    """Where a changed file currently sits relative to the index."""

    STAGED = "staged"
    UNSTAGED = "unstaged"
    UNTRACKED = "untracked"
    CONFLICTED = "conflicted"


class FileDelta(StrEnum):
    """What happened to a file, independent of whether it is staged."""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"
    UNKNOWN = "unknown"


class LineKind(StrEnum):
    """A diff line's leading character, as libgit2 reports it.

    The three EOFNL members are libgit2's "no newline at end of file" markers.
    They are listed so an origin round-trips unchanged rather than raising, and
    every renderer treats them the way it always has: anything that is not
    ADDED or REMOVED draws as context.
    """

    ADDED = "+"
    REMOVED = "-"
    CONTEXT = " "
    ADDED_EOFNL = ">"
    REMOVED_EOFNL = "<"
    CONTEXT_EOFNL = "="

    @classmethod
    def _missing_(cls, value: object) -> LineKind:
        # A diff that cannot be rendered is worse than one rendered as context.
        return cls.CONTEXT


@dataclass
class Commit:
    oid: str
    message: str
    author: str
    timestamp: datetime
    parents: list[str]


@dataclass
class Branch:
    name: str
    is_remote: bool
    is_head: bool
    target_oid: str


@dataclass
class RemoteBranchDeleteResult:
    branch: str  # full shorthand, e.g. "origin/feature-a"
    ok: bool
    message: str


@dataclass
class Stash:
    index: int
    message: str
    oid: str
    timestamp: datetime | None = None


@dataclass
class Tag:
    name: str
    target_oid: str
    is_annotated: bool
    message: str | None
    tagger: str | None
    timestamp: datetime | None


@dataclass
class FileStat:
    path: str
    added: int
    deleted: int


@dataclass
class CommitStat:
    oid: str
    author: str
    timestamp: datetime
    files: list[FileStat]


@dataclass
class FileStatus:
    path: str
    status: StagingState
    delta: FileDelta


@dataclass
class Hunk:
    header: str
    lines: list[tuple[LineKind, str]]


@dataclass
class ReflogEntry:
    """One movement of a ref, as recorded in its reflog.

    The reflog is what makes a destructive operation recoverable: `oid_old` is
    the state the ref was in before, and it stays reachable even when nothing
    else points at it.
    """

    index: int  # 0 is the most recent — the `n` in `HEAD@{n}`
    oid_new: str  # where the ref moved to
    oid_old: str | None  # where it was; None on the entry that created the ref
    operation: str  # "commit", "reset", "checkout", "rebase (finish)", …
    summary: str  # the rest of the message, after the operation
    committer: str
    timestamp: datetime
    is_orphaned: bool = False
    # True when no branch, tag or other ref can reach `oid_new` any more. The
    # reflog is then the only way back to it, and gc will collect it when the
    # entry expires — which is what makes these the entries worth finding.


@dataclass
class BlameLine:
    """One line of a file with the commit that last touched it.

    `is_run_start` marks the first line of each consecutive run from the same
    commit, so a view can show the attribution once per run instead of
    repeating it on every line.
    """

    line_no: int  # 1-based, within the blamed revision of the file
    text: str  # the line itself, without its trailing newline
    commit_oid: str
    author: str
    timestamp: datetime
    summary: str  # first line of that commit's message
    is_run_start: bool


@dataclass
class Remote:
    name: str
    fetch_url: str
    push_url: str


@dataclass
class Submodule:
    path: str
    url: str
    head_sha: str | None


@dataclass
class LocalBranchInfo:
    name: str
    upstream: str | None
    last_commit_sha: str
    last_commit_message: str


class RepoState(StrEnum):
    CLEAN = "CLEAN"
    MERGING = "MERGING"
    REBASING = "REBASING"
    CHERRY_PICKING = "CHERRY_PICKING"
    REVERTING = "REVERTING"
    DETACHED_HEAD = "DETACHED_HEAD"


@dataclass(frozen=True)
class RepoStateInfo:
    state: RepoState
    head_branch: str | None


class MergeStrategy(StrEnum):
    NO_FF = "NO_FF"
    FF_ONLY = "FF_ONLY"
    ALLOW_FF = "ALLOW_FF"


class ResetMode(StrEnum):
    SOFT = "SOFT"
    MIXED = "MIXED"
    HARD = "HARD"


@dataclass(frozen=True)
class MergeAnalysisResult:
    can_ff: bool
    is_up_to_date: bool


@dataclass(frozen=True)
class Worktree:
    path: str
    branch: str | None  # None when HEAD is detached
    head_sha: str
    is_locked: bool
    lock_reason: str | None  # None when not locked or no reason given
    is_bare: bool
    is_main: bool  # True for the primary worktree
