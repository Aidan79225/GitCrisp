from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Literal

WORKING_TREE_OID = "WORKING_TREE"


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
    status: Literal["staged", "unstaged", "untracked", "conflicted"]
    delta: Literal["added", "modified", "deleted", "renamed", "unknown"]


@dataclass
class Hunk:
    header: str
    lines: list[tuple[Literal["+", "-", " "], str]]


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


class RepoState(str, Enum):
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


class MergeStrategy(str, Enum):
    NO_FF = "NO_FF"
    FF_ONLY = "FF_ONLY"
    ALLOW_FF = "ALLOW_FF"


class ResetMode(str, Enum):
    SOFT = "SOFT"
    MIXED = "MIXED"
    HARD = "HARD"


@dataclass(frozen=True)
class MergeAnalysisResult:
    can_ff: bool
    is_up_to_date: bool
