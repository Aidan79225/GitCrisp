from __future__ import annotations
from dataclasses import dataclass, field
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
class FileStatus:
    path: str
    status: Literal["staged", "unstaged", "untracked", "conflicted"]
    delta: Literal["added", "modified", "deleted", "renamed", "unknown"]


@dataclass
class Hunk:
    header: str
    lines: list[tuple[Literal["+", "-", " "], str]]
