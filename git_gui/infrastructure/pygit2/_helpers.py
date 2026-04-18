# git_gui/infrastructure/pygit2/_helpers.py
"""Pure helpers for the pygit2 adapter family. No pygit2.Repository instance
state, no shared mutable state — these are free functions that the mixins
call during diff synthesis, submodule detection, and entity conversion."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal
import os

import pygit2

from git_gui.domain.entities import Commit, Hunk


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


def _synthesise_conflict_hunk(workdir: str, path: str) -> list[Hunk]:
    """Read a conflicted file and return one hunk per conflict block (<<<<<<<...>>>>>>>)."""
    full = os.path.join(workdir, path)
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return []
    if not lines:
        return []

    hunks: list[Hunk] = []
    block: list[tuple[str, str]] = []
    block_start = 0
    in_conflict = False
    in_ours = False

    for i, raw in enumerate(lines):
        line = raw if raw.endswith("\n") else raw + "\n"
        if line.startswith("<<<<<<<"):
            in_conflict = True
            in_ours = True
            block_start = i + 1  # 1-based
            block.append((" ", line))
        elif line.startswith("=======") and in_conflict:
            in_ours = False
            block.append((" ", line))
        elif line.startswith(">>>>>>>") and in_conflict:
            block.append((" ", line))
            n = len(block)
            hunks.append(Hunk(
                header=f"@@ -{block_start},{n} +{block_start},{n} @@",
                lines=block,
            ))
            block = []
            in_conflict = False
        elif in_conflict:
            if in_ours:
                block.append(("-", line))
            else:
                block.append(("+", line))

    return hunks


def _resolve_gitdir(path: str) -> str:
    """Resolve a submodule workdir path to its real .git directory.

    Handles three cases:

    1. ``<path>/.git`` is a directory → normal repo, return path unchanged.
    2. ``<path>/.git`` is a gitlink file containing ``gitdir: <rel>`` → follow
       the gitlink to the real gitdir under ``<parent>/.git/modules/<name>/``.
    3. ``<path>/.git`` does not exist (uninitialized / broken submodule
       checkout) → walk up the directory tree looking for a parent repo
       whose ``.gitmodules`` lists ``<path>``, and use that parent's
       ``.git/modules/<relpath>/`` as the gitdir.

    Without this, pygit2's own discovery walks up past the submodule workdir
    and opens the *parent* repo, so the UI shows the parent's commit graph
    when the user opens a submodule.
    """
    dot_git = os.path.join(path, ".git")

    # Case 1: normal repo with .git directory → passthrough
    if os.path.isdir(dot_git):
        return path

    # Case 2: gitlink file (initialized submodule)
    if os.path.isfile(dot_git):
        try:
            with open(dot_git, "r", encoding="utf-8") as f:
                content = f.read().strip()
        except OSError:
            return path
        if content.startswith("gitdir:"):
            rel = content[len("gitdir:"):].strip()
            return os.path.normpath(os.path.join(path, rel))
        return path

    # Case 3: no .git at all — try to find a parent repo whose .gitmodules
    # lists this path as a submodule.
    abs_path = os.path.abspath(path)
    current = os.path.dirname(abs_path)
    while True:
        parent_git = os.path.join(current, ".git")
        gitmodules_path = os.path.join(current, ".gitmodules")
        if os.path.isdir(parent_git) and os.path.isfile(gitmodules_path):
            rel_path = os.path.relpath(abs_path, current).replace("\\", "/")
            try:
                with open(gitmodules_path, "r", encoding="utf-8") as f:
                    modules_content = f.read()
            except OSError:
                return path
            for line in modules_content.splitlines():
                stripped = line.strip()
                if stripped.startswith("path"):
                    _, _, value = stripped.partition("=")
                    if value.strip() == rel_path:
                        candidate = os.path.join(parent_git, "modules", rel_path)
                        if os.path.isdir(candidate):
                            return os.path.normpath(candidate)
                        break
            return path  # matched a parent but no gitdir — give up
        next_parent = os.path.dirname(current)
        if next_parent == current:
            break
        current = next_parent

    return path


def _parse_gitmodules_paths(workdir: str) -> list[str]:
    """Parse ``.gitmodules`` under ``workdir`` and return the list of submodule paths."""
    gitmodules = os.path.join(workdir, ".gitmodules")
    if not os.path.isfile(gitmodules):
        return []
    paths: list[str] = []
    try:
        with open(gitmodules, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("path"):
            _, _, value = stripped.partition("=")
            value = value.strip()
            if value:
                paths.append(value)
    return paths


def _read_submodule_head_oid(parent_workdir: str, sub_path: str) -> str | None:
    """Return the submodule's current HEAD oid, working even for empty workdirs.

    Uses ``_resolve_gitdir`` to find the submodule's real gitdir (either via a
    ``.git`` gitlink file or by walking up to the parent's ``.git/modules/``
    entry), opens it, and returns the HEAD oid. Returns ``None`` if the
    submodule can't be opened or is unborn.
    """
    abs_path = os.path.join(parent_workdir, sub_path)
    resolved = _resolve_gitdir(abs_path)
    if resolved == abs_path:
        # _resolve_gitdir couldn't find a gitdir for this submodule
        return None
    try:
        sub_repo = pygit2.Repository(resolved)
        if sub_repo.head_is_unborn:
            return None
        return str(sub_repo.head.target)
    except Exception:
        return None


def _submodule_diff_hunk(old_oid: str, new_oid: str) -> Hunk:
    """Build a two-line hunk that mirrors git's ``Subproject commit`` diff format."""
    return Hunk(
        header="@@ -1,1 +1,1 @@",
        lines=[
            ("-", f"Subproject commit {old_oid}\n"),
            ("+", f"Subproject commit {new_oid}\n"),
        ],
    )
