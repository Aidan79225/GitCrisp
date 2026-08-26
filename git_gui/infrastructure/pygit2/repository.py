# git_gui/infrastructure/pygit2/repository.py
from __future__ import annotations

import subprocess
import threading

import pygit2

from git_gui.infrastructure.commit_ops_cli import CommitOpsCli
from git_gui.infrastructure.file_history_cli import FileHistoryCli
from git_gui.infrastructure.pygit2._helpers import _resolve_gitdir
from git_gui.infrastructure.pygit2.blame_ops import BlameOps
from git_gui.infrastructure.pygit2.branch_ops import BranchOps
from git_gui.infrastructure.pygit2.commit_ops import CommitOps
from git_gui.infrastructure.pygit2.diff_ops import DiffOps
from git_gui.infrastructure.pygit2.merge_rebase_ops import MergeRebaseOps
from git_gui.infrastructure.pygit2.remote_ops import RemoteOps
from git_gui.infrastructure.pygit2.repo_state_ops import RepoStateOps
from git_gui.infrastructure.pygit2.stage_ops import StageOps
from git_gui.infrastructure.pygit2.stash_ops import StashOps
from git_gui.infrastructure.pygit2.submodule_ops import SubmoduleOps
from git_gui.infrastructure.pygit2.tag_ops import TagOps
from git_gui.infrastructure.pygit2.worktree_ops import WorktreeOps


class Pygit2Repository(
    BlameOps,
    BranchOps,
    CommitOps,
    DiffOps,
    StageOps,
    TagOps,
    StashOps,
    MergeRebaseOps,
    RemoteOps,
    SubmoduleOps,
    RepoStateOps,
    WorktreeOps,
):
    """Composite pygit2 adapter. Every public method lives on one of the
    mixin base classes; this class provides only construction."""

    def __init__(self, path: str) -> None:
        self._repo = pygit2.Repository(_resolve_gitdir(path))
        self._commit_ops = CommitOpsCli(self._repo.workdir)
        self._file_history = FileHistoryCli(self._repo.workdir)
        # Remote-op cancellation state, consumed by RemoteOps: the active
        # push/pull/fetch subprocess and a lock guarding it (the UI thread
        # terminates it while a worker thread runs the op).
        self._remote_proc_lock = threading.Lock()
        self._active_remote_proc: subprocess.Popen | None = None
        self._remote_cancel_requested = False
