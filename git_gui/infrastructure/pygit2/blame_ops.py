# git_gui/infrastructure/pygit2/blame_ops.py
from __future__ import annotations

from datetime import datetime

import pygit2

from git_gui.domain.entities import BlameLine


class BlameOps:
    """Per-line authorship for a single file at a single revision.

    Mixin — not instantiable on its own. Relies on `self._repo` set up by the
    composite class.
    """

    _repo: pygit2.Repository  # provided by the composite

    def get_blame(self, path: str, *, at_oid: str | None = None) -> list[BlameLine]:
        """Attribute every line of `path` to the commit that last touched it.

        Blames the file as of `at_oid`, or HEAD when it is None. The content
        comes from the same revision's blob rather than the working tree, so
        the lines and the attribution always describe the same snapshot.
        """
        if at_oid is None:
            if self._repo.head_is_unborn:
                raise ValueError("Nothing to blame — this branch has no commits yet.")
            at_oid = str(self._repo.head.target)

        blob = self._read_blob(path, at_oid)
        if blob.is_binary:
            raise ValueError(f"Cannot blame a binary file: {path}")

        try:
            blame = self._repo.blame(path, newest_commit=pygit2.Oid(hex=at_oid))
        except KeyError as e:
            raise ValueError(f"{path} does not exist at {at_oid[:8]}") from e

        text_lines = blob.data.decode("utf-8", errors="replace").splitlines()

        # One lookup per distinct commit, not per line: blame reports the
        # committer, but a blame view shows the author, and the commit also
        # carries the summary we want alongside it.
        meta_cache: dict[str, tuple[str, datetime, str]] = {}
        lines: list[BlameLine] = []

        for hunk in blame:
            oid = str(hunk.final_commit_id)
            if oid not in meta_cache:
                meta_cache[oid] = self._commit_meta(oid, hunk)
            author, timestamp, summary = meta_cache[oid]

            start = hunk.final_start_line_number  # 1-based
            for offset in range(hunk.lines_in_hunk):
                line_no = start + offset
                if line_no > len(text_lines):
                    # Defensive: blame and the blob should agree on line count.
                    break
                lines.append(
                    BlameLine(
                        line_no=line_no,
                        text=text_lines[line_no - 1],
                        commit_oid=oid,
                        author=author,
                        timestamp=timestamp,
                        summary=summary,
                        is_run_start=offset == 0,
                    )
                )

        lines.sort(key=lambda line: line.line_no)
        return lines

    # ── helpers ──────────────────────────────────────────────────────────────

    def _read_blob(self, path: str, oid: str) -> pygit2.Blob:
        try:
            obj = self._repo.revparse_single(f"{oid}:{path}")
        except KeyError as e:
            raise ValueError(f"{path} does not exist at {oid[:8]}") from e
        if not isinstance(obj, pygit2.Blob):
            raise ValueError(f"Not a file: {path}")
        return obj

    def _commit_meta(self, oid: str, hunk) -> tuple[str, datetime, str]:
        """Author name, authored time and subject line for a blamed commit.

        Falls back to the committer blame already gave us if the commit itself
        cannot be read — a shallow clone can blame to a commit it lacks.
        """
        commit = self._repo.get(oid)
        if commit is None:
            sig = hunk.final_committer
            return (sig.name or "", datetime.fromtimestamp(sig.time), "")
        return (
            commit.author.name or "",
            datetime.fromtimestamp(commit.author.time),
            commit.message.split("\n")[0],
        )
