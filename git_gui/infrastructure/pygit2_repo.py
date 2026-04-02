from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal

import pygit2

from git_gui.domain.entities import (
    Branch, Commit, FileStatus, Hunk, Stash, WORKING_TREE_OID,
)


_STATUS_MAP: dict[int, tuple[Literal["staged","unstaged","untracked","conflicted"],
                              Literal["added","modified","deleted","renamed","unknown"]]] = {
    pygit2.GIT_STATUS_INDEX_NEW:        ("staged",   "added"),
    pygit2.GIT_STATUS_INDEX_MODIFIED:   ("staged",   "modified"),
    pygit2.GIT_STATUS_INDEX_DELETED:    ("staged",   "deleted"),
    pygit2.GIT_STATUS_INDEX_RENAMED:    ("staged",   "renamed"),
    pygit2.GIT_STATUS_WT_NEW:           ("untracked","added"),
    pygit2.GIT_STATUS_WT_MODIFIED:      ("unstaged", "modified"),
    pygit2.GIT_STATUS_WT_DELETED:       ("unstaged", "deleted"),
    pygit2.GIT_STATUS_WT_RENAMED:       ("unstaged", "renamed"),
    pygit2.GIT_STATUS_CONFLICTED:       ("conflicted","unknown"),
}


def _map_status(flags: int) -> tuple[str, str]:
    for flag, mapping in _STATUS_MAP.items():
        if flags & flag:
            return mapping
    return ("unstaged", "unknown")


def _commit_to_entity(c: pygit2.Commit) -> Commit:
    ts = datetime.fromtimestamp(c.commit_time, tz=timezone.utc)
    return Commit(
        oid=str(c.id),
        message=c.message.strip(),
        author=f"{c.author.name} <{c.author.email}>",
        timestamp=ts,
        parents=[str(p.id) for p in c.parents],
    )


def _diff_to_hunks(patch: pygit2.Patch) -> list[Hunk]:
    result = []
    for hunk in patch.hunks:
        lines = [(line.origin, line.content) for line in hunk.lines]
        result.append(Hunk(header=hunk.header, lines=lines))
    return result


class Pygit2Repository:
    def __init__(self, path: str) -> None:
        self._repo = pygit2.Repository(path)

    # ------------------------------------------------------------------ reads

    def get_commits(self, limit: int) -> list[Commit]:
        if self._repo.head_is_unborn:
            return []
        walker = self._repo.walk(
            self._repo.head.target,
            pygit2.GIT_SORT_TOPOLOGICAL | pygit2.GIT_SORT_TIME,
        )
        return [_commit_to_entity(c) for c, _ in zip(walker, range(limit))]

    def get_branches(self) -> list[Branch]:
        branches: list[Branch] = []
        head_target = None if self._repo.head_is_unborn else str(self._repo.head.target)

        for name in self._repo.branches.local:
            ref = self._repo.branches.local[name]
            branches.append(Branch(
                name=name,
                is_remote=False,
                is_head=(str(ref.target) == head_target),
                target_oid=str(ref.target),
            ))
        for name in self._repo.branches.remote:
            ref = self._repo.branches.remote[name]
            branches.append(Branch(
                name=name,
                is_remote=True,
                is_head=False,
                target_oid=str(ref.target),
            ))
        return branches

    def get_stashes(self) -> list[Stash]:
        result = []
        for i, stash in enumerate(self._repo.listall_stashes()):
            result.append(Stash(index=i, message=stash.message, oid=str(stash.commit_id)))
        return result

    def get_commit_files(self, oid: str) -> list[FileStatus]:
        commit = self._repo.get(oid)
        if commit.parents:
            diff = self._repo.diff(commit.parents[0].tree, commit.tree)
        else:
            # Initial commit: diff from empty tree to commit tree so files show as added
            empty_tree_oid = self._repo.TreeBuilder().write()
            empty_tree = self._repo.get(empty_tree_oid)
            diff = self._repo.diff(empty_tree, commit.tree)
        files = []
        for patch in diff:
            delta = patch.delta
            path = delta.new_file.path or delta.old_file.path
            delta_type = {
                pygit2.GIT_DELTA_ADDED:    "added",
                pygit2.GIT_DELTA_DELETED:  "deleted",
                pygit2.GIT_DELTA_MODIFIED: "modified",
                pygit2.GIT_DELTA_RENAMED:  "renamed",
            }.get(delta.status, "unknown")
            files.append(FileStatus(path=path, status="staged", delta=delta_type))
        return files

    def get_file_diff(self, oid: str, path: str) -> list[Hunk]:
        if oid == WORKING_TREE_OID:
            diff = self._repo.diff()
        else:
            commit = self._repo.get(oid)
            if commit.parents:
                diff = self._repo.diff(commit.parents[0].tree, commit.tree)
            else:
                # Initial commit: diff from empty tree so lines show as added
                empty_tree_oid = self._repo.TreeBuilder().write()
                empty_tree = self._repo.get(empty_tree_oid)
                diff = self._repo.diff(empty_tree, commit.tree)
        for patch in diff:
            if patch.delta.new_file.path == path or patch.delta.old_file.path == path:
                return _diff_to_hunks(patch)
        return []

    def get_working_tree(self) -> list[FileStatus]:
        files = []
        for path, flags in self._repo.status().items():
            if flags == pygit2.GIT_STATUS_CURRENT:
                continue
            status, delta = _map_status(flags)
            files.append(FileStatus(path=path, status=status, delta=delta))
        return files
