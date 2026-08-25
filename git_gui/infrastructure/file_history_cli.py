from __future__ import annotations

import shutil
import subprocess

from git_gui.resources import subprocess_kwargs


class FileHistoryError(Exception):
    """Failure from `git log -- <path>`."""


class FileHistoryCli:
    """Thin wrapper around `git log -- <path>` executed via subprocess.

    pygit2's revwalk has no pathspec limit and no `--follow`, so filtering a
    walk by path in-process means diffing every commit against its first
    parent — linear in history length and blind to renames. The git CLI does
    both natively, so we shell out for the OID list and let the caller hydrate
    each one through the normal `get_commit` path.
    """

    def __init__(self, repo_workdir: str, git_executable: str = "git") -> None:
        self._cwd = repo_workdir
        self._git = git_executable

    def commit_oids(
        self, path: str, limit: int, skip: int = 0, *, follow: bool = True
    ) -> list[str]:
        """OIDs of commits touching `path`, newest first.

        With `follow`, history continues across renames — the path is tracked
        back to whatever it was called before. git only supports `--follow` for
        a single pathspec, which is all we ever pass.

        Paging is done by over-fetching and slicing rather than with `--skip`:
        git applies `--skip` before `--follow` re-derives the pathspec, so
        `--skip=1 --follow` drops a commit from the *unfiltered* walk and
        returns the same first result again. Over-fetching re-walks the earlier
        pages, which is cheap next to getting the wrong commits.
        """
        if shutil.which(self._git) is None:
            raise FileHistoryError(f"`{self._git}` executable not found on PATH")

        args = [self._git, "log", "--format=%H", f"--max-count={skip + limit}"]
        if follow:
            args.append("--follow")
        # `--` stops git treating a path that looks like a ref as one.
        args += ["--", path]

        try:
            proc = subprocess.run(
                args,
                cwd=self._cwd,
                capture_output=True,
                text=True,
                **subprocess_kwargs(),
            )
        except OSError as e:
            raise FileHistoryError(f"Failed to run git log: {e}") from e

        if proc.returncode != 0:
            raise FileHistoryError((proc.stderr or "git log failed").strip())

        oids = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        return oids[skip:]
