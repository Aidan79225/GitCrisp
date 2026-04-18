from __future__ import annotations
import os
import subprocess

import pygit2

from git_gui.resources import subprocess_kwargs


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
                env=self._git_env,
                check=True, capture_output=True, **subprocess_kwargs(),
            )
            self._repo.index.read()

    def unstage_hunk(self, path: str, hunk_header: str) -> None:
        patch = self._build_hunk_patch(path, hunk_header, staged=True)
        if patch:
            subprocess.run(
                ["git", "apply", "--cached", "--reverse"],
                input=patch.encode("utf-8"), cwd=self._repo.workdir,
                env=self._git_env,
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
                env=self._git_env,
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
