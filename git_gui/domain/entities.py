from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
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
