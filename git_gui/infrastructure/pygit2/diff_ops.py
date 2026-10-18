from __future__ import annotations

import logging
import subprocess

import pygit2

from git_gui.domain.entities import (
    WORKING_TREE_OID,
    FileDelta,
    FileStatus,
    Hunk,
    StagingState,
)
from git_gui.infrastructure.pygit2._helpers import (
    _diff_to_hunks,
    _head_tree,
    _map_statuses,
    _patch_path,
    _patches_for_path,
    _staged_diff,
    _submodule_diff_hunk,
    _synthesise_conflict_hunk,
    _synthesise_untracked_hunk,
)
from git_gui.resources import subprocess_kwargs

logger = logging.getLogger(__name__)


class DiffOps:
    """Diff, hunk, and file-status queries for a commit, the staged
    index, and the working tree — including untracked/conflict synthesis.

    Mixin — not instantiable on its own. Relies on `self._repo` set up
    by the composite class, and on CommitOps' `_diff_against_parent`.
    """

    _repo: pygit2.Repository  # provided by the composite

    def get_file_diff(self, oid: str, path: str) -> list[Hunk]:
        if oid == WORKING_TREE_OID:
            hunks = _hunks_for_path(self._repo.diff(), path)
            if hunks:
                return hunks
            # Not found in tracked diff, or found with 0 hunks — check status
            try:
                status = self._repo.status_file(path)
            except KeyError:
                return []
            if status & pygit2.GIT_STATUS_CONFLICTED:
                hunks = _synthesise_conflict_hunk(self._repo.workdir, path)
                if hunks:
                    return hunks
                # Conflict markers resolved — diff working tree against HEAD
                return self._diff_workfile_against_head(path)
            if status & pygit2.GIT_STATUS_WT_NEW:
                return _synthesise_untracked_hunk(self._repo.workdir, path)
            return []
        return _hunks_for_path(self._diff_against_parent(oid), path)

    def get_working_tree_diff_map(
        self, paths: list[str] | None = None
    ) -> dict[str, dict[StagingState, list[Hunk]]]:
        """Return {path: {"staged": [...], "unstaged": [...]}} for changed files.

        Computes the full staged diff and unstaged diff exactly once each.

        When *paths* is given, only those paths have their (relatively
        expensive) hunks computed — the rest are skipped entirely. This keeps
        the working-tree view responsive when thousands of files have changed
        but only a bounded subset is actually displayed.
        """
        wanted = set(paths) if paths is not None else None
        result: dict[str, dict[StagingState, list[Hunk]]] = {}

        # Staged: index vs HEAD
        try:
            for patch in _staged_diff(self._repo):
                path = _patch_path(patch)
                if not path:
                    continue
                if wanted is not None and path not in wanted:
                    continue
                entry = result.setdefault(
                    path, {StagingState.STAGED: [], StagingState.UNSTAGED: []}
                )
                # Extended, not set: a type change is a deletion and an
                # addition of the one path.
                entry[StagingState.STAGED].extend(_diff_to_hunks(patch))
        except Exception as e:
            logger.warning("Failed to compute staged diff map: %s", e)

        # Unstaged: workdir vs index
        try:
            for patch in self._repo.diff():
                path = _patch_path(patch)
                if not path:
                    continue
                if wanted is not None and path not in wanted:
                    continue
                entry = result.setdefault(
                    path, {StagingState.STAGED: [], StagingState.UNSTAGED: []}
                )
                hunks = _diff_to_hunks(patch)
                if not hunks:
                    try:
                        status = self._repo.status_file(path)
                    except KeyError:
                        status = 0
                    if status & pygit2.GIT_STATUS_CONFLICTED:
                        conflict_hunks = _synthesise_conflict_hunk(self._repo.workdir, path)
                        if conflict_hunks:
                            hunks = conflict_hunks
                        else:
                            hunks = self._diff_workfile_against_head(path)
                entry[StagingState.UNSTAGED].extend(hunks)
        except Exception as e:
            logger.warning("Failed to compute unstaged diff map: %s", e)

        # Untracked files
        try:
            for path, status in self._repo.status().items():
                if status & pygit2.GIT_STATUS_WT_NEW:
                    if wanted is not None and path not in wanted:
                        continue
                    result.setdefault(path, {StagingState.STAGED: [], StagingState.UNSTAGED: []})
                    result[path][StagingState.UNSTAGED] = _synthesise_untracked_hunk(
                        self._repo.workdir, path
                    )
        except Exception as e:
            logger.warning("Failed to enumerate untracked files for diff map: %s", e)

        # Submodule changes that pygit2's diff() misses for uninitialized workdirs.
        # Override any existing empty entry — pygit2 sometimes returns an empty
        # patch for a submodule, which would leave the UI with no hunks to show.
        for sub_path, tree_oid, index_oid, actual_oid in self._detect_diverged_submodules():
            if wanted is not None and sub_path not in wanted:
                continue
            entry = result.setdefault(
                sub_path, {StagingState.STAGED: [], StagingState.UNSTAGED: []}
            )
            if index_oid != tree_oid:
                entry[StagingState.STAGED] = [_submodule_diff_hunk(tree_oid, index_oid)]
            if actual_oid != index_oid:
                entry[StagingState.UNSTAGED] = [_submodule_diff_hunk(index_oid, actual_oid)]

        return result

    def _diff_workfile_against_head(self, path: str) -> list[Hunk]:
        """Diff the working-tree file against the HEAD version."""
        try:
            diff = self._repo.diff(_head_tree(self._repo), flags=pygit2.GIT_DIFF_FORCE_TEXT)
            return _hunks_for_path(diff, path)
        except Exception as e:
            logger.warning("Failed to diff %r against HEAD: %s", path, e)
        return []

    def get_staged_diff(self, path: str) -> list[Hunk]:
        # When the index has conflicts, diff_to_tree may fail — return empty.
        try:
            return _hunks_for_path(_staged_diff(self._repo), path)
        except Exception as e:
            logger.warning("Failed to compute staged diff for %r: %s", path, e)
        return []

    def get_working_tree(self) -> list[FileStatus]:
        files = []
        for path, flags in self._repo.status().items():
            if flags == pygit2.GIT_STATUS_CURRENT:
                continue
            for status, delta in _map_statuses(flags):
                files.append(FileStatus(path=path, status=status, delta=delta))

        # Surface submodule changes that pygit2's status() misses when the
        # submodule workdir has no .git link file.
        seen = {f.path for f in files}
        for sub_path, tree_oid, index_oid, actual_oid in self._detect_diverged_submodules():
            if sub_path in seen:
                continue
            if index_oid != tree_oid:
                files.append(
                    FileStatus(path=sub_path, status=StagingState.STAGED, delta=FileDelta.MODIFIED)
                )
            if actual_oid != index_oid:
                files.append(
                    FileStatus(
                        path=sub_path, status=StagingState.UNSTAGED, delta=FileDelta.MODIFIED
                    )
                )

        return files

    def is_dirty(self) -> bool:
        # GIT_OPTIONAL_LOCKS=0 stops `git status` from refreshing/rewriting
        # .git/index as a side effect. Without it, this dirty check (run on
        # every auto-reload) rewrites the index, which trips the
        # RepoChangeDetector's file watcher and schedules another reload —
        # a self-perpetuating refresh loop that makes the commit-detail pane
        # jump every few seconds.
        env = {**self._git_env, "GIT_OPTIONAL_LOCKS": "0"}
        # Bytes, not text: only emptiness matters, and decoding raw UTF-8
        # paths (core.quotepath=false) in a non-UTF-8 locale loses stdout.
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            cwd=self._repo.workdir,
            env=env,
            **subprocess_kwargs(),
        )
        return bool(result.stdout.strip())


def _hunks_for_path(diff: pygit2.Diff, path: str) -> list[Hunk]:
    return [hunk for patch in _patches_for_path(diff, path) for hunk in _diff_to_hunks(patch)]
