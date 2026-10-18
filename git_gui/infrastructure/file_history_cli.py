from __future__ import annotations

import shutil

from git_gui.infrastructure.git_process import git_run_dir, pinned_git_env, run_git


class FileHistoryError(Exception):
    """Failure from `git log -- <path>`."""


class FileHistoryCli:
    """Thin wrapper around `git log -- <path>` executed via subprocess.

    pygit2's revwalk has no pathspec limit and no `--follow`, so filtering a
    walk by path in-process means diffing every commit against its first
    parent — linear in history length and blind to renames. The git CLI does
    both natively, so we shell out for the OID list and let the caller hydrate
    each one through the normal `get_commit` path.

    Pass `git_dir` to pin git to that repository. Without it git discovers
    the repository from `repo_workdir`, which for a submodule whose `.git`
    link is missing walks up to the parent and reads the wrong history.
    """

    def __init__(
        self, repo_workdir: str | None, git_executable: str = "git", *, git_dir: str | None = None
    ) -> None:
        self._cwd = git_run_dir(repo_workdir, git_dir)
        self._work_tree = repo_workdir
        self._git = git_executable
        self._git_dir = git_dir

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

        # `--literal-pathspecs` keeps `[`, `*` and `?` in a file name from
        # globbing other files into its history.
        args = [
            self._git,
            "--literal-pathspecs",
            "log",
            "--format=%H",
            f"--max-count={skip + limit}",
            # Explicit either way: a user's `log.follow=true` would otherwise
            # follow renames even when the caller asked not to.
            "--follow" if follow else "--no-follow",
        ]
        # `--` stops git treating a path that looks like a ref as one.
        args += ["--", path]

        try:
            proc = run_git(args, cwd=self._cwd, env=pinned_git_env(self._git_dir, self._work_tree))
        except OSError as e:
            raise FileHistoryError(f"Failed to run git log: {e}") from e

        if proc.returncode != 0:
            raise FileHistoryError((proc.stderr or "git log failed").strip())

        oids = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        return oids[skip:]
