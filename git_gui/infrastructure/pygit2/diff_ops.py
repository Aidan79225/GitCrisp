# git_gui/infrastructure/pygit2/diff_ops.py
from __future__ import annotations
import logging
import subprocess

import pygit2

from git_gui.resources import subprocess_kwargs
from git_gui.domain.entities import FileStatus, Hunk, WORKING_TREE_OID
from git_gui.infrastructure.pygit2._helpers import (
    _diff_to_hunks,
    _map_statuses,
    _synthesise_untracked_hunk,
    _synthesise_conflict_hunk,
    _submodule_diff_hunk,
)

logger = logging.getLogger(__name__)


class DiffOps:
    """Diff, hunk, and file-status queries for a commit, the staged
    index, and the working tree — including untracked/conflict synthesis.

    Mixin — not instantiable on its own. Relies on `self._repo` set up
    by the composite class.
    """
    _repo: pygit2.Repository  # provided by the composite

    def get_file_diff(self, oid: str, path: str) -> list[Hunk]:
        if oid == WORKING_TREE_OID:
            diff = self._repo.diff()
            for patch in diff:
                if patch.delta.new_file.path == path or patch.delta.old_file.path == path:
                    hunks = _diff_to_hunks(patch)
                    if hunks:
                        return hunks
                    # Patch found but 0 hunks (e.g. conflicted) — fall through
                    break
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
        commit = self._repo.get(oid)
        if commit.parents:
            diff = self._repo.diff(commit.parents[0].tree, commit.tree)
        else:
            empty_tree_oid = self._repo.TreeBuilder().write()
            empty_tree = self._repo.get(empty_tree_oid)
            diff = self._repo.diff(empty_tree, commit.tree)
        for patch in diff:
            if patch.delta.new_file.path == path or patch.delta.old_file.path == path:
                return _diff_to_hunks(patch)
        return []

    def get_working_tree_diff_map(self) -> dict[str, dict[str, list[Hunk]]]:
        """Return {path: {"staged": [...], "unstaged": [...]}} for every changed file.

        Computes the full staged diff and unstaged diff exactly once each.
        """
        result: dict[str, dict[str, list[Hunk]]] = {}

        # Staged: index vs HEAD
        try:
            if self._repo.head_is_unborn:
                empty_tree_oid = self._repo.TreeBuilder().write()
                empty_tree = self._repo.get(empty_tree_oid)
                staged_diff = self._repo.index.diff_to_tree(empty_tree)
            else:
                head_commit = self._repo.head.peel(pygit2.Commit)
                staged_diff = self._repo.index.diff_to_tree(head_commit.tree)
            for patch in staged_diff:
                path = patch.delta.new_file.path or patch.delta.old_file.path
                if not path:
                    continue
                result.setdefault(path, {"staged": [], "unstaged": []})
                result[path]["staged"] = _diff_to_hunks(patch)
        except Exception as e:
            logger.warning("Failed to compute staged diff map: %s", e)

        # Unstaged: workdir vs index
        try:
            unstaged_diff = self._repo.diff()
            for patch in unstaged_diff:
                path = patch.delta.new_file.path or patch.delta.old_file.path
                if not path:
                    continue
                result.setdefault(path, {"staged": [], "unstaged": []})
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
                result[path]["unstaged"] = hunks
        except Exception as e:
            logger.warning("Failed to compute unstaged diff map: %s", e)

        # Untracked files
        try:
            for path, status in self._repo.status().items():
                if status & pygit2.GIT_STATUS_WT_NEW:
                    result.setdefault(path, {"staged": [], "unstaged": []})
                    result[path]["unstaged"] = _synthesise_untracked_hunk(self._repo.workdir, path)
        except Exception as e:
            logger.warning("Failed to enumerate untracked files for diff map: %s", e)

        # Submodule changes that pygit2's diff() misses for uninitialized workdirs.
        # Override any existing empty entry — pygit2 sometimes returns an empty
        # patch for a submodule, which would leave the UI with no hunks to show.
        for sub_path, tree_oid, index_oid, actual_oid in self._detect_diverged_submodules():
            entry = result.setdefault(sub_path, {"staged": [], "unstaged": []})
            if index_oid != tree_oid:
                entry["staged"] = [_submodule_diff_hunk(tree_oid, index_oid)]
            if actual_oid != index_oid:
                entry["unstaged"] = [_submodule_diff_hunk(index_oid, actual_oid)]

        return result

    def _diff_workfile_against_head(self, path: str) -> list[Hunk]:
        """Diff the working-tree file against the HEAD version."""
        try:
            head_commit = self._repo.head.peel(pygit2.Commit)
            diff = self._repo.diff(head_commit.tree, flags=pygit2.GIT_DIFF_FORCE_TEXT)
            for patch in diff:
                if patch.delta.new_file.path == path or patch.delta.old_file.path == path:
                    return _diff_to_hunks(patch)
        except Exception as e:
            logger.warning("Failed to diff %r against HEAD: %s", path, e)
        return []

    def get_staged_diff(self, path: str) -> list[Hunk]:
        # Diff the index against HEAD tree to show what is staged for commit.
        # For unborn HEAD (no commits yet), diff against an empty tree.
        # When the index has conflicts, diff_to_tree may fail — return empty.
        try:
            if self._repo.head_is_unborn:
                empty_tree_oid = self._repo.TreeBuilder().write()
                empty_tree = self._repo.get(empty_tree_oid)
                diff = self._repo.index.diff_to_tree(empty_tree)
            else:
                head_commit = self._repo.head.peel(pygit2.Commit)
                diff = self._repo.index.diff_to_tree(head_commit.tree)
            for patch in diff:
                if patch.delta.new_file.path == path or patch.delta.old_file.path == path:
                    return _diff_to_hunks(patch)
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
                files.append(FileStatus(path=sub_path, status="staged", delta="modified"))
            if actual_oid != index_oid:
                files.append(FileStatus(path=sub_path, status="unstaged", delta="modified"))

        return files

    def is_dirty(self) -> bool:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True,
            cwd=self._repo.workdir, env=self._git_env, **subprocess_kwargs(),
        )
        return bool(result.stdout.strip())
