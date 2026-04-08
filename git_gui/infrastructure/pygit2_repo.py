from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal
import os
import subprocess

import pygit2

from git_gui.resources import subprocess_kwargs
from git_gui.domain.entities import (
    Branch, Commit, CommitStat, FileStat, FileStatus, Hunk, Remote, Stash, Submodule, Tag, WORKING_TREE_OID,
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


def _map_statuses(flags: int) -> list[tuple[str, str]]:
    """Return all matching statuses for the given flags (can be multiple for partial staging)."""
    results = []
    for flag, mapping in _STATUS_MAP.items():
        if flags & flag:
            results.append(mapping)
    return results or [("unstaged", "unknown")]


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


_UNTRACKED_MAX_LINES = 5000
_UNTRACKED_MAX_BYTES = 1_048_576


def _synthesise_untracked_hunk(workdir: str, path: str) -> list[Hunk]:
    full = os.path.join(workdir, path)
    try:
        size = os.path.getsize(full)
        with open(full, "rb") as f:
            head = f.read(8192)
        is_binary = b"\x00" in head
        if is_binary:
            return [Hunk(header="@@ -0,0 +1,1 @@",
                         lines=[("+", "Binary file\n")])]
        if size > _UNTRACKED_MAX_BYTES:
            return [Hunk(header="@@ -0,0 +1,1 @@",
                         lines=[("+", f"Large file ({size} bytes)\n")])]
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        lines = text.splitlines(keepends=True)
        if len(lines) > _UNTRACKED_MAX_LINES:
            return [Hunk(header="@@ -0,0 +1,1 @@",
                         lines=[("+", f"Large file ({len(lines)} lines, {size} bytes)\n")])]
        if not lines:
            return []
        return [Hunk(
            header=f"@@ -0,0 +1,{len(lines)} @@",
            lines=[("+", line if line.endswith("\n") else line + "\n") for line in lines],
        )]
    except OSError:
        return []


class Pygit2Repository:
    def __init__(self, path: str) -> None:
        self._repo = pygit2.Repository(path)

    # ------------------------------------------------------------------ reads

    def get_commits(self, limit: int, skip: int = 0, extra_tips: list[str] | None = None) -> list[Commit]:
        if self._repo.head_is_unborn:
            return []

        walker = self._repo.walk(
            self._repo.head.target,
            pygit2.GIT_SORT_TOPOLOGICAL | pygit2.GIT_SORT_TIME,
        )

        # Also push upstream remote branch if current branch has one
        try:
            head_ref = self._repo.head
            if not head_ref.name.startswith("refs/heads/"):
                pass  # detached HEAD — no upstream
            else:
                local_name = head_ref.name[len("refs/heads/"):]
                local_branch = self._repo.branches.local[local_name]
                if local_branch.upstream:
                    walker.push(local_branch.upstream.resolve().target)
        except (KeyError, Exception):
            pass

        # Push extra tips (e.g. clicked branch)
        for tip in (extra_tips or []):
            try:
                walker.push(pygit2.Oid(hex=tip))
            except (ValueError, Exception):
                pass

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
            for patch in diff:
                if patch.delta.new_file.path == path or patch.delta.old_file.path == path:
                    return _diff_to_hunks(patch)
            # Not found in tracked diff — check if it's an untracked file
            try:
                status = self._repo.status_file(path)
            except KeyError:
                return []
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

    def get_tags(self) -> list[Tag]:
        tags: list[Tag] = []
        for ref_name in self._repo.references:
            if not ref_name.startswith("refs/tags/"):
                continue
            ref = self._repo.references[ref_name]
            name = ref_name[len("refs/tags/"):]
            target = self._repo.get(ref.target)
            if isinstance(target, pygit2.Tag):
                # Annotated tag — peel to get the commit OID
                peeled = ref.peel(pygit2.Commit)
                commit_oid = str(peeled.id)
                ts = datetime.fromtimestamp(target.tagger.time, tz=timezone.utc) if target.tagger else None
                tagger_str = f"{target.tagger.name} <{target.tagger.email}>" if target.tagger else None
                tags.append(Tag(
                    name=name,
                    target_oid=commit_oid,
                    is_annotated=True,
                    message=target.message.strip() if target.message else None,
                    tagger=tagger_str,
                    timestamp=ts,
                ))
            else:
                # Lightweight tag — target is a commit directly
                tags.append(Tag(
                    name=name,
                    target_oid=str(ref.target),
                    is_annotated=False,
                    message=None,
                    tagger=None,
                    timestamp=None,
                ))
        return tags

    def get_remote_tags(self, remote: str) -> list[str]:
        try:
            result = subprocess.run(
                ["git", "ls-remote", "--tags", remote],
                capture_output=True, text=True,
                cwd=self._repo.workdir, **subprocess_kwargs(),
            )
            if result.returncode != 0:
                return []
            tags: list[str] = []
            for line in result.stdout.strip().splitlines():
                # Format: "<hash>\trefs/tags/<name>"
                parts = line.split("\t")
                if len(parts) != 2:
                    continue
                ref = parts[1]
                if not ref.startswith("refs/tags/"):
                    continue
                name = ref[len("refs/tags/"):]
                # Skip dereferenced entries like "v1.0^{}"
                if name.endswith("^{}"):
                    continue
                tags.append(name)
            return tags
        except Exception:
            return []

    def get_commit_stats(self, since: datetime | None = None, until: datetime | None = None) -> list[CommitStat]:
        cmd = ["git", "log", "--numstat", "--format=__COMMIT__%n%H%n%aN <%aE>%n%aI"]
        if since:
            cmd.append(f"--since={since.isoformat()}")
        if until:
            cmd.append(f"--until={until.isoformat()}")
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                cwd=self._repo.workdir, **subprocess_kwargs(),
            )
            if result.returncode != 0:
                return []
        except Exception:
            return []

        stats: list[CommitStat] = []
        current_oid: str | None = None
        current_author: str | None = None
        current_ts: datetime | None = None
        current_files: list[FileStat] = []
        state = "expect_marker"  # expect_marker | oid | author | date | files

        def flush() -> None:
            if current_oid and current_author and current_ts is not None:
                stats.append(CommitStat(
                    oid=current_oid,
                    author=current_author,
                    timestamp=current_ts,
                    files=list(current_files),
                ))

        for raw_line in result.stdout.splitlines():
            line = raw_line.rstrip("\r")
            if line == "__COMMIT__":
                flush()
                current_oid = None
                current_author = None
                current_ts = None
                current_files = []
                state = "oid"
                continue
            if state == "oid":
                current_oid = line
                state = "author"
                continue
            if state == "author":
                current_author = line
                state = "date"
                continue
            if state == "date":
                try:
                    current_ts = datetime.fromisoformat(line)
                except ValueError:
                    current_ts = None
                state = "files"
                continue
            if state == "files":
                if not line.strip():
                    continue
                # numstat format: "<added>\t<deleted>\t<path>"
                parts = line.split("\t")
                if len(parts) != 3:
                    continue
                added_str, deleted_str, path = parts
                try:
                    added = int(added_str) if added_str != "-" else 0
                    deleted = int(deleted_str) if deleted_str != "-" else 0
                except ValueError:
                    continue
                current_files.append(FileStat(path=path, added=added, deleted=deleted))

        flush()
        return stats

    def get_working_tree(self) -> list[FileStatus]:
        files = []
        for path, flags in self._repo.status().items():
            if flags == pygit2.GIT_STATUS_CURRENT:
                continue
            for status, delta in _map_statuses(flags):
                files.append(FileStatus(path=path, status=status, delta=delta))
        return files

    def is_dirty(self) -> bool:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True,
            cwd=self._repo.workdir, **subprocess_kwargs(),
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
            full = os.path.join(self._repo.workdir, path)
            if os.path.exists(full):
                self._repo.index.add(path)
            else:
                # Working-tree deletion → stage the deletion
                try:
                    self._repo.index.remove(path)
                except (KeyError, OSError):
                    pass
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
                check=True, capture_output=True, **subprocess_kwargs(),
            )
            self._repo.index.read()

    def unstage_hunk(self, path: str, hunk_header: str) -> None:
        patch = self._build_hunk_patch(path, hunk_header, staged=True)
        if patch:
            subprocess.run(
                ["git", "apply", "--cached", "--reverse"],
                input=patch.encode("utf-8"), cwd=self._repo.workdir,
                check=True, capture_output=True, **subprocess_kwargs(),
            )
            self._repo.index.read()

    def discard_file(self, path: str) -> None:
        full = os.path.join(self._repo.workdir, path)
        head_has_blob = False
        head_commit = None
        if not self._repo.head_is_unborn:
            head_commit = self._repo.head.peel(pygit2.Commit)
            try:
                head_commit.tree[path]
                head_has_blob = True
            except KeyError:
                head_has_blob = False

        if head_has_blob:
            entry = head_commit.tree[path]
            self._repo.index.add(
                pygit2.IndexEntry(path, entry.id, entry.filemode)
            )
            self._repo.index.write()
            self._repo.index.read()
            blob = self._repo.get(entry.id)
            os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
            with open(full, "wb") as f:
                f.write(blob.data)
        else:
            try:
                self._repo.index.remove(path)
                self._repo.index.write()
                self._repo.index.read()
            except (KeyError, OSError):
                pass
            if os.path.exists(full):
                os.remove(full)

    def discard_hunk(self, path: str, hunk_header: str) -> None:
        patch = self._build_hunk_patch(path, hunk_header, staged=False)
        if patch:
            subprocess.run(
                ["git", "apply", "--reverse"],
                input=patch.encode("utf-8"), cwd=self._repo.workdir,
                check=True, capture_output=True, **subprocess_kwargs(),
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
        self._run_git("push", remote, branch)

    def pull(self, remote: str, branch: str) -> None:
        self._run_git("pull", "--rebase", remote, branch)

    def fetch(self, remote: str) -> None:
        self._run_git("fetch", remote)

    def fetch_all_prune(self) -> None:
        self._run_git("fetch", "--all", "--prune")

    def _run_git(self, *args: str) -> None:
        result = subprocess.run(
            ["git", *args],
            cwd=self._repo.workdir, capture_output=True, text=True,
            **subprocess_kwargs(),
        )
        if result.returncode != 0:
            msg = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
            raise RuntimeError(msg)

    def create_tag(self, name: str, oid: str, message: str | None = None) -> None:
        target = pygit2.Oid(hex=oid)
        if message:
            sig = self._get_signature()
            self._repo.create_tag(name, target, pygit2.GIT_OBJECT_COMMIT, sig, message)
        else:
            self._repo.references.create(f"refs/tags/{name}", target)

    def delete_tag(self, name: str) -> None:
        self._repo.references.delete(f"refs/tags/{name}")

    def push_tag(self, remote: str, name: str) -> None:
        self._run_git("push", remote, f"refs/tags/{name}")

    def stash(self, message: str) -> None:
        sig = self._get_signature()
        self._repo.stash(sig, message=message, include_untracked=True)

    def pop_stash(self, index: int) -> None:
        self._repo.stash_pop(index=index)

    def apply_stash(self, index: int) -> None:
        self._repo.stash_apply(index=index)

    def drop_stash(self, index: int) -> None:
        self._repo.stash_drop(index=index)

    # ----- Remotes -----

    def list_remotes(self) -> list[Remote]:
        result: list[Remote] = []
        for r in self._repo.remotes:
            push_url = r.push_url if r.push_url else r.url
            result.append(Remote(name=r.name, fetch_url=r.url, push_url=push_url))
        return result

    def add_remote(self, name: str, url: str) -> None:
        self._repo.remotes.create(name, url)

    def remove_remote(self, name: str) -> None:
        self._repo.remotes.delete(name)

    def rename_remote(self, old_name: str, new_name: str) -> None:
        self._repo.remotes.rename(old_name, new_name)

    def set_remote_url(self, name: str, url: str) -> None:
        self._repo.remotes.set_url(name, url)

    # ----- Submodules -----

    def _submodule_cli(self):
        from git_gui.infrastructure.submodule_cli import SubmoduleCli
        return SubmoduleCli(self._repo.workdir)

    def list_submodules(self) -> list[Submodule]:
        result: list[Submodule] = []
        try:
            sm_paths = list(self._repo.listall_submodules())
        except Exception:
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
            except Exception:
                pass

        # Get head SHAs via git ls-files -s (gitlink entries have mode 160000)
        sha_map: dict[str, str] = {}
        try:
            ls_result = subprocess.run(
                ["git", "ls-files", "-s", "--"] + sm_paths,
                capture_output=True, text=True,
                cwd=self._repo.workdir, **subprocess_kwargs(),
            )
            for line in ls_result.stdout.splitlines():
                # Format: "160000 <sha> <stage>\t<path>"
                line_parts = line.split("\t", 1)
                if len(line_parts) == 2:
                    fields = line_parts[0].split()
                    if len(fields) >= 2 and fields[0] == "160000":
                        sha_map[line_parts[1]] = fields[1]
        except Exception:
            pass

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
