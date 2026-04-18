from __future__ import annotations
from datetime import datetime, timezone
import logging
import os
import subprocess

import pygit2

from git_gui.resources import subprocess_kwargs
from git_gui.infrastructure.commit_ops_cli import CommitOpsCli
from git_gui.infrastructure.pygit2.stash_ops import StashOps
from git_gui.infrastructure.pygit2.tag_ops import TagOps
from git_gui.infrastructure.pygit2.branch_ops import BranchOps
from git_gui.infrastructure.pygit2.remote_ops import RemoteOps
from git_gui.infrastructure.pygit2.repo_state_ops import RepoStateOps
from git_gui.infrastructure.pygit2.stage_ops import StageOps
from git_gui.infrastructure.pygit2.commit_ops import CommitOps
from git_gui.infrastructure.pygit2.merge_rebase_ops import MergeRebaseOps
from git_gui.infrastructure.pygit2.diff_ops import DiffOps
from git_gui.infrastructure.pygit2._helpers import (
    _map_statuses,
    _commit_to_entity,
    _diff_to_hunks,
    _synthesise_untracked_hunk,
    _synthesise_conflict_hunk,
    _resolve_gitdir,
    _parse_gitmodules_paths,
    _read_submodule_head_oid,
    _submodule_diff_hunk,
)

logger = logging.getLogger(__name__)
from git_gui.domain.entities import (
    Branch, Commit, CommitStat, FileStat, FileStatus, Hunk, LocalBranchInfo, MergeAnalysisResult, MergeStrategy, Remote, RepoState, RepoStateInfo, ResetMode, Stash, Submodule, Tag, WORKING_TREE_OID,
)


class Pygit2Repository(StashOps, TagOps, BranchOps, RemoteOps, RepoStateOps, StageOps, CommitOps, MergeRebaseOps, DiffOps):
    def __init__(self, path: str) -> None:
        self._repo = pygit2.Repository(_resolve_gitdir(path))
        self._commit_ops = CommitOpsCli(self._repo.workdir)

    def _detect_diverged_submodules(self) -> list[tuple[str, str, str, str]]:
        """Return ``(path, tree_oid, index_oid, actual_oid)`` for each submodule
        where at least one of the three oids differs.

        Surfaces submodule changes that pygit2's ``status()``/``diff()`` misses
        when the submodule workdir has no ``.git`` link file (an "uninitialized"
        or broken checkout). The gitdir is still found via ``_resolve_gitdir``.
        """
        if self._repo.head_is_unborn:
            return []
        result: list[tuple[str, str, str, str]] = []
        try:
            head_tree = self._repo.head.peel(pygit2.Commit).tree
            index = self._repo.index
            for sub_path in _parse_gitmodules_paths(self._repo.workdir):
                try:
                    tree_oid = str(head_tree[sub_path].id)
                except KeyError:
                    continue
                try:
                    index_oid = str(index[sub_path].id)
                except KeyError:
                    index_oid = tree_oid
                actual_oid = _read_submodule_head_oid(self._repo.workdir, sub_path)
                if actual_oid is None:
                    continue
                if tree_oid != index_oid or index_oid != actual_oid:
                    result.append((sub_path, tree_oid, index_oid, actual_oid))
        except Exception as e:
            logger.warning("Failed to detect submodule changes: %s", e)
        return result

    # ----------------------------------------------------------------- writes

    # ----- Submodules -----

    def _submodule_cli(self):
        from git_gui.infrastructure.submodule_cli import SubmoduleCli
        return SubmoduleCli(self._repo.workdir)

    def list_submodules(self) -> list[Submodule]:
        result: list[Submodule] = []
        try:
            sm_paths = list(self._repo.listall_submodules())
        except Exception as e:
            logger.warning("Failed to list submodules: %s", e)
            return result
        if not sm_paths:
            return result

        # Parse URLs from .gitmodules config file
        import os
        url_map: dict[str, str] = {}
        gitmodules_path = os.path.join(self._repo.workdir, ".gitmodules")
        if os.path.exists(gitmodules_path):
            try:
                cfg = pygit2.Config(gitmodules_path)
                for entry in cfg:
                    # entry.name is like "submodule.libs/foo.url"
                    parts = entry.name.split(".")
                    if len(parts) >= 3 and parts[0] == "submodule" and parts[-1] == "url":
                        sm_path = ".".join(parts[1:-1])
                        url_map[sm_path] = entry.value
            except Exception as e:
                logger.warning("Failed to parse .gitmodules at %r: %s", gitmodules_path, e)

        # Get head SHAs via git ls-files -s (gitlink entries have mode 160000)
        sha_map: dict[str, str] = {}
        try:
            ls_result = subprocess.run(
                ["git", "ls-files", "-s", "--"] + sm_paths,
                capture_output=True, text=True,
                cwd=self._repo.workdir, env=self._git_env, **subprocess_kwargs(),
            )
            for line in ls_result.stdout.splitlines():
                # Format: "160000 <sha> <stage>\t<path>"
                line_parts = line.split("\t", 1)
                if len(line_parts) == 2:
                    fields = line_parts[0].split()
                    if len(fields) >= 2 and fields[0] == "160000":
                        sha_map[line_parts[1]] = fields[1]
        except Exception as e:
            logger.warning("Failed to read submodule SHAs via git ls-files: %s", e)

        for path in sm_paths:
            url = url_map.get(path, "")
            head = sha_map.get(path)
            result.append(Submodule(path=path, url=url, head_sha=head))
        return result

    def add_submodule(self, path: str, url: str) -> None:
        self._submodule_cli().add(path=path, url=url)

    def remove_submodule(self, path: str) -> None:
        self._submodule_cli().remove(path)

    def set_submodule_url(self, path: str, url: str) -> None:
        self._submodule_cli().set_url(path, url)
