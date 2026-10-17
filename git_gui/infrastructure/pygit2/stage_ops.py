from __future__ import annotations

import os
import subprocess

import pygit2

from git_gui.domain.entities import LineKind
from git_gui.resources import subprocess_kwargs

# Their content is already the whole "\ No newline at end of file" line, and a
# patch writes that line with no origin character in front.
_NO_NEWLINE_MARKERS = frozenset(
    {LineKind.ADDED_EOFNL, LineKind.REMOVED_EOFNL, LineKind.CONTEXT_EOFNL}
)


class StageOps:
    """Index / staging operations: stage, unstage, hunk-level stage/discard.

    Mixin — not instantiable on its own. Relies on `self._repo` set up
    by the composite class.
    """

    _repo: pygit2.Repository  # provided by the composite

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
                    self._repo.index.add(pygit2.IndexEntry(path, entry.id, entry.filemode))
                else:
                    self._repo.index.remove(path)
            self._repo.index.write()

    def stage_hunk(self, path: str, hunk_header: str) -> None:
        patch = self._build_hunk_patch(path, hunk_header, staged=False)
        if patch:
            subprocess.run(
                ["git", "apply", "--cached"],
                input=patch,
                cwd=self._repo.workdir,
                env=self._git_env,
                check=True,
                capture_output=True,
                **subprocess_kwargs(),
            )
            self._repo.index.read()

    def unstage_hunk(self, path: str, hunk_header: str) -> None:
        patch = self._build_hunk_patch(path, hunk_header, staged=True)
        if patch:
            subprocess.run(
                ["git", "apply", "--cached", "--reverse"],
                input=patch,
                cwd=self._repo.workdir,
                env=self._git_env,
                check=True,
                capture_output=True,
                **subprocess_kwargs(),
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
            self._repo.index.add(pygit2.IndexEntry(path, entry.id, entry.filemode))
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
                input=patch,
                cwd=self._repo.workdir,
                env=self._git_env,
                check=True,
                capture_output=True,
                **subprocess_kwargs(),
            )
            self._repo.index.read()

    def _build_hunk_patch(self, path: str, hunk_header: str, staged: bool) -> bytes | None:
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
                    return _single_hunk_patch(path, hunk)
        return None


def _single_hunk_patch(path: str, hunk: pygit2.DiffHunk) -> bytes:
    # Built from raw_content: `content` is a lossy UTF-8 decode, so a Latin-1
    # or Big5 line rebuilt from it no longer matches the file.
    name = os.fsencode(path)
    lines = [b"--- a/" + name + b"\n", b"+++ b/" + name + b"\n", hunk.header.encode()]
    for line in hunk.lines:
        origin = b"" if line.origin in _NO_NEWLINE_MARKERS else line.origin.encode()
        lines.append(origin + line.raw_content)
    if not lines[-1].endswith(b"\n"):
        lines[-1] += b"\n"
    return b"".join(lines)
