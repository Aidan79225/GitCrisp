from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal
import subprocess

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

    def get_commits(self, limit: int, skip: int = 0) -> list[Commit]:
        if self._repo.head_is_unborn:
            return []

        walker = self._repo.walk(
            self._repo.head.target,
            pygit2.GIT_SORT_TOPOLOGICAL | pygit2.GIT_SORT_TIME,
        )

        # Also push all branch tips so remote-only commits are included
        for name in self._repo.branches.local:
            ref = self._repo.branches.local[name]
            walker.push(ref.resolve().target)
        for name in self._repo.branches.remote:
            ref = self._repo.branches.remote[name]
            walker.push(ref.resolve().target)

        # Skip first N commits
        for _ in range(skip):
            try:
                next(walker)
            except StopIteration:
                return []
        return [_commit_to_entity(c) for c, _ in zip(walker, range(limit))]

    def get_commit(self, oid: str) -> Commit:
        return _commit_to_entity(self._repo.get(oid))

    def get_branches(self) -> list[Branch]:
        branches: list[Branch] = []
        # Compare HEAD's ref name (e.g. "refs/heads/main"), not target oid,
        # so only the actual checked-out branch is marked as head.
        try:
            head_ref_name = self._repo.head.name if not self._repo.head_is_unborn else None
        except Exception:
            head_ref_name = None

        for name in self._repo.branches.local:
            ref = self._repo.branches.local[name]
            branches.append(Branch(
                name=name,
                is_remote=False,
                is_head=(ref.name == head_ref_name),
                target_oid=str(ref.resolve().target),
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

    def get_staged_diff(self, path: str) -> list[Hunk]:
        # Diff the index against HEAD tree to show what is staged for commit.
        # For unborn HEAD (no commits yet), diff against an empty tree.
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
        return []

    def get_working_tree(self) -> list[FileStatus]:
        files = []
        for path, flags in self._repo.status().items():
            if flags == pygit2.GIT_STATUS_CURRENT:
                continue
            status, delta = _map_status(flags)
            files.append(FileStatus(path=path, status=status, delta=delta))
        return files

    def is_dirty(self) -> bool:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True,
            cwd=self._repo.workdir,
        )
        return bool(result.stdout.strip())

    def get_head_oid(self) -> str | None:
        if self._repo.head_is_unborn:
            return None
        return str(self._repo.head.target)

    # ----------------------------------------------------------------- helpers

    def _get_signature(self) -> pygit2.Signature:
        try:
            return self._repo.default_signature
        except pygit2.GitError:
            return pygit2.Signature("Git GUI", "gitgui@localhost")

    # ----------------------------------------------------------------- writes

    def stage(self, paths: list[str]) -> None:
        for path in paths:
            self._repo.index.add(path)
        self._repo.index.write()

    def unstage(self, paths: list[str]) -> None:
        if self._repo.head_is_unborn:
            for path in paths:
                self._repo.index.remove(path)
            self._repo.index.write()
        else:
            head_commit = self._repo.head.peel(pygit2.Commit)
            for path in paths:
                if path in head_commit.tree:
                    entry = head_commit.tree[path]
                    self._repo.index.add(
                        pygit2.IndexEntry(path, entry.id, entry.filemode)
                    )
                else:
                    self._repo.index.remove(path)
            self._repo.index.write()

    def stage_hunk(self, path: str, hunk_header: str) -> None:
        patch = self._build_hunk_patch(path, hunk_header, staged=False)
        if patch:
            subprocess.run(
                ["git", "apply", "--cached"],
                input=patch.encode("utf-8"), cwd=self._repo.workdir,
                check=True, capture_output=True,
            )
            self._repo.index.read()

    def unstage_hunk(self, path: str, hunk_header: str) -> None:
        patch = self._build_hunk_patch(path, hunk_header, staged=True)
        if patch:
            subprocess.run(
                ["git", "apply", "--cached", "--reverse"],
                input=patch.encode("utf-8"), cwd=self._repo.workdir,
                check=True, capture_output=True,
            )
            self._repo.index.read()

    def _build_hunk_patch(self, path: str, hunk_header: str, staged: bool) -> str | None:
        if staged:
            if self._repo.head_is_unborn:
                empty_tree_oid = self._repo.TreeBuilder().write()
                empty_tree = self._repo.get(empty_tree_oid)
                diff = self._repo.index.diff_to_tree(empty_tree)
            else:
                head_commit = self._repo.head.peel(pygit2.Commit)
                diff = self._repo.index.diff_to_tree(head_commit.tree)
        else:
            diff = self._repo.diff()

        for patch in diff:
            if patch.delta.new_file.path != path and patch.delta.old_file.path != path:
                continue
            for hunk in patch.hunks:
                if hunk.header == hunk_header:
                    # Build minimal patch: diff header + single hunk
                    lines = [f"--- a/{path}\n", f"+++ b/{path}\n"]
                    lines.append(hunk.header)
                    for line in hunk.lines:
                        lines.append(f"{line.origin}{line.content}")
                    # Ensure last line ends with newline
                    if lines and not lines[-1].endswith("\n"):
                        lines[-1] += "\n"
                    return "".join(lines)
        return None

    def commit(self, message: str) -> "Commit":
        self._repo.index.write()
        tree = self._repo.index.write_tree()
        sig = self._get_signature()
        parents = [] if self._repo.head_is_unborn else [self._repo.head.target]
        oid = self._repo.create_commit("HEAD", sig, sig, message, tree, parents)
        return _commit_to_entity(self._repo.get(oid))

    def create_branch(self, name: str, from_oid: str) -> "Branch":
        commit = self._repo.get(from_oid)
        self._repo.create_branch(name, commit, False)
        return Branch(name=name, is_remote=False, is_head=False, target_oid=from_oid)

    def checkout(self, branch: str) -> None:
        ref = self._repo.branches.local[branch]
        self._repo.checkout(ref)

    def checkout_commit(self, oid: str) -> None:
        commit = self._repo.get(oid)
        self._repo.checkout_tree(commit)
        self._repo.set_head(commit.id)

    def checkout_remote_branch(self, remote_branch: str) -> None:
        # "origin/feature" → local branch "feature" tracking "origin/feature"
        parts = remote_branch.split("/", 1)
        local_name = parts[1] if len(parts) > 1 else remote_branch
        remote_ref = self._repo.branches.remote[remote_branch]
        # Create local branch at the same commit
        local_ref = self._repo.branches.local.create(local_name, self._repo.get(remote_ref.target))
        local_ref.upstream = remote_ref
        self._repo.checkout(local_ref)

    def delete_branch(self, name: str) -> None:
        self._repo.branches.local[name].delete()

    def merge(self, branch: str) -> None:
        # Support both local ("main") and remote-tracking ("origin/main") branches
        if branch in self._repo.branches.local:
            ref = self._repo.branches.local[branch]
        else:
            ref = self._repo.branches.remote[branch]
        merge_result, _ = self._repo.merge_analysis(ref.target)
        if merge_result & pygit2.GIT_MERGE_ANALYSIS_FASTFORWARD:
            self._repo.checkout_tree(self._repo.get(ref.target))
            self._repo.head.set_target(ref.target)
        elif merge_result & pygit2.GIT_MERGE_ANALYSIS_NORMAL:
            self._repo.merge(ref.target)
            if not self._repo.index.conflicts:
                self._repo.index.write()
                tree = self._repo.index.write_tree()
                sig = self._get_signature()
                self._repo.create_commit(
                    "HEAD", sig, sig,
                    f"Merge branch '{branch}'",
                    tree,
                    [self._repo.head.target, ref.target],
                )
                self._repo.state_cleanup()

    def rebase(self, branch: str) -> None:
        onto_ref = self._repo.branches.local[branch]
        rebase = self._repo.rebase(onto=onto_ref.target)
        while True:
            op = rebase.next()
            if op is None:
                break
        rebase.finish(self._get_signature())

    def push(self, remote: str, branch: str) -> None:
        subprocess.run(
            ["git", "push", remote, branch],
            cwd=self._repo.workdir, check=True, capture_output=True,
        )

    def pull(self, remote: str, branch: str) -> None:
        subprocess.run(
            ["git", "pull", "--rebase", remote, branch],
            cwd=self._repo.workdir, check=True, capture_output=True,
        )

    def fetch(self, remote: str) -> None:
        subprocess.run(
            ["git", "fetch", remote],
            cwd=self._repo.workdir, check=True, capture_output=True,
        )

    def fetch_all_prune(self) -> None:
        subprocess.run(
            ["git", "fetch", "--all", "--prune"],
            cwd=self._repo.workdir, check=True, capture_output=True,
        )

    def stash(self, message: str) -> None:
        sig = self._get_signature()
        self._repo.stash(sig, message=message, include_untracked=True)

    def pop_stash(self, index: int) -> None:
        self._repo.stash_pop(index=index)

    def apply_stash(self, index: int) -> None:
        self._repo.stash_apply(index=index)

    def drop_stash(self, index: int) -> None:
        self._repo.stash_drop(index=index)
