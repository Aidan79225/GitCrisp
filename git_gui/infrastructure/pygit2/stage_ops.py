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
            # lexists: a symlink whose target is missing is still there to stage.
            if os.path.lexists(full):
                self._repo.index.add(path)
            else:
                self._stage_deletion(path)
        self._repo.index.write()

    def _stage_deletion(self, path: str) -> None:
        index = self._repo.index
        # remove() drops only the stage-0 entry, and a conflicted path has
        # none: deleting the file resolves a modify/delete conflict only once
        # its stage 1-3 entries go too.
        if index.conflicts is not None and path in index.conflicts:
            del index.conflicts[path]
            return
        try:
            index.remove(path)
        except (KeyError, OSError):
            pass

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
        self._apply_patch(patch, "--cached")

    def unstage_hunk(self, path: str, hunk_header: str) -> None:
        patch = self._build_hunk_patch(path, hunk_header, staged=True)
        self._apply_patch(patch, "--cached", "--reverse")

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

        # The work tree goes first and the index second: when the file cannot
        # be replaced (on Windows, another program holding it open), the
        # discard then fails with the staged change still in place.
        if head_has_blob:
            self._restore_from_head(path, "--worktree")
            self._restore_from_head(path, "--staged")
        else:
            if os.path.lexists(full):
                os.remove(full)
            try:
                self._repo.index.remove(path)
                self._repo.index.write()
                self._repo.index.read()
            except (KeyError, OSError):
                pass

    def _restore_from_head(self, path: str, where: str) -> None:
        # git CLI, not a raw blob write: a restore applies eol/autocrlf and
        # smudge filters (LFS), restores the file mode, and replaces a symlink
        # rather than write through it. Literal pathspecs keep `*` or `[` in a
        # name from discarding other files' changes too. Not `git checkout
        # HEAD -- path`: it writes the index even when the file write fails.
        self._run_git_checked(
            ["--literal-pathspecs", "restore", "--source=HEAD", where, "--", path]
        )
        self._repo.index.read()

    def discard_hunk(self, path: str, hunk_header: str) -> None:
        patch = self._build_hunk_patch(path, hunk_header, staged=False)
        self._apply_patch(patch, "--reverse")

    def _apply_patch(self, patch: bytes, *options: str) -> None:
        self._run_git_checked(["apply", *options], stdin=patch)
        self._repo.index.read()

    def _run_git_checked(self, args: list[str], stdin: bytes | None = None) -> None:
        """Run git, raising its own explanation of a failure.

        A CalledProcessError says only "returned non-zero exit status 1",
        which tells the user nothing about a held index.lock or a patch that
        no longer applies.
        """
        result = subprocess.run(
            ["git", *args],
            input=stdin,
            cwd=self._repo.workdir,
            env=self._git_env,
            capture_output=True,
            **subprocess_kwargs(),
        )
        if result.returncode != 0:
            reason = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(reason or f"git exited with status {result.returncode}")

    def _build_hunk_patch(self, path: str, hunk_header: str, staged: bool) -> bytes:
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
                    return _single_hunk_patch(path, patch.delta, hunk)
        # Returning quietly let the checkbox show a stage that never happened.
        raise RuntimeError(f"hunk {hunk_header.strip()} not found in {path}")


def _single_hunk_patch(path: str, delta: pygit2.DiffDelta, hunk: pygit2.DiffHunk) -> bytes:
    # Built from raw_content: `content` is a lossy UTF-8 decode, so a Latin-1
    # or Big5 line rebuilt from it no longer matches the file.
    lines = [*_file_header(os.fsencode(path), delta), hunk.header.encode()]
    for line in hunk.lines:
        origin = b"" if line.origin in _NO_NEWLINE_MARKERS else line.origin.encode()
        lines.append(origin + line.raw_content)
    if not lines[-1].endswith(b"\n"):
        lines[-1] += b"\n"
    return b"".join(lines)


def _file_header(name: bytes, delta: pygit2.DiffDelta) -> list[bytes]:
    if delta.status != pygit2.GIT_DELTA_DELETED:
        return [b"--- a/" + name + b"\n", b"+++ b/" + name + b"\n"]
    # Without /dev/null git apply stages an empty file rather than the
    # deletion, and the mode line lets a reversed apply restore the file mode.
    return [
        b"diff --git a/" + name + b" b/" + name + b"\n",
        b"deleted file mode %o\n" % delta.old_file.mode,
        b"--- a/" + name + b"\n",
        b"+++ /dev/null\n",
    ]
