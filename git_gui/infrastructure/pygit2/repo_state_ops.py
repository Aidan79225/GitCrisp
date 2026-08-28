from __future__ import annotations

import os

import pygit2

from git_gui.domain.entities import RepoState, RepoStateInfo
from git_gui.resources import git_ssh_env

# Keyed by `pygit2.enums.RepositoryState` — the legacy `pygit2.GIT_REPOSITORY_*`
# constants this used to read were removed in pygit2 1.20. Because they were
# looked up with `getattr(..., None)`, their removal degraded silently: every
# state mapped to CLEAN, so a conflicted merge or rebase reported no operation
# in progress and the conflict banner never appeared.
_REPO_STATE_MAP: dict[pygit2.enums.RepositoryState, RepoState] = {
    pygit2.enums.RepositoryState.NONE: RepoState.CLEAN,
    pygit2.enums.RepositoryState.MERGE: RepoState.MERGING,
    pygit2.enums.RepositoryState.REVERT: RepoState.REVERTING,
    pygit2.enums.RepositoryState.REVERT_SEQUENCE: RepoState.REVERTING,
    pygit2.enums.RepositoryState.CHERRYPICK: RepoState.CHERRY_PICKING,
    pygit2.enums.RepositoryState.CHERRYPICK_SEQUENCE: RepoState.CHERRY_PICKING,
    pygit2.enums.RepositoryState.REBASE: RepoState.REBASING,
    pygit2.enums.RepositoryState.REBASE_INTERACTIVE: RepoState.REBASING,
    pygit2.enums.RepositoryState.REBASE_MERGE: RepoState.REBASING,
    pygit2.enums.RepositoryState.APPLY_MAILBOX: RepoState.CLEAN,
    pygit2.enums.RepositoryState.APPLY_MAILBOX_OR_REBASE: RepoState.REBASING,
}


class RepoStateOps:
    """Repository-level state reads (HEAD, state, MERGE_HEAD) and the
    `_git_env` property that other mixins' subprocess calls rely on.

    Mixin — not instantiable on its own. Relies on `self._repo` set up
    by the composite class.
    """

    _repo: pygit2.Repository  # provided by the composite

    @property
    def _git_env(self) -> dict:
        """Environment dict forcing git CLI to use this repo's gitdir/worktree.

        Without this, ``subprocess.run(["git", ...], cwd=workdir)`` lets git
        walk up looking for ``.git`` — which for a submodule workdir that
        has no ``.git`` file lands on the *parent* repo and runs the command
        against the wrong remote.

        Also carries ``GIT_SSH_COMMAND`` so remote ops (push/pull/fetch) don't
        fail on first-time SSH host-key verification.
        """
        env = git_ssh_env()
        env["GIT_DIR"] = self._repo.path
        if self._repo.workdir:
            env["GIT_WORK_TREE"] = self._repo.workdir
        return env

    def get_head_oid(self) -> str | None:
        if self._repo.head_is_unborn:
            return None
        return str(self._repo.head.target)

    def repo_state(self) -> RepoStateInfo:
        # Unborn HEAD (fresh `git init`, no commits yet) — CLEAN with no branch.
        if self._repo.head_is_unborn:
            return RepoStateInfo(state=RepoState.CLEAN, head_branch=None)

        # Check operation state FIRST — git detaches HEAD during rebase,
        # but we want to report REBASING, not DETACHED_HEAD.
        mapped = _REPO_STATE_MAP.get(self._repo.state(), RepoState.CLEAN)

        # If in an active operation (merge/rebase/etc), report that state
        # even if HEAD is detached (rebase detaches HEAD).
        if mapped != RepoState.CLEAN:
            head_branch = None if self._repo.head_is_detached else self._repo.head.shorthand
            return RepoStateInfo(state=mapped, head_branch=head_branch)

        # No operation in progress — check for plain detached HEAD
        if self._repo.head_is_detached:
            return RepoStateInfo(state=RepoState.DETACHED_HEAD, head_branch=None)

        return RepoStateInfo(state=RepoState.CLEAN, head_branch=self._repo.head.shorthand)

    def get_merge_head(self) -> str | None:
        merge_head_path = os.path.join(self._repo.path, "MERGE_HEAD")
        if not os.path.exists(merge_head_path):
            return None
        with open(merge_head_path) as f:
            return f.readline().strip()

    def get_merge_msg(self) -> str | None:
        merge_msg_path = os.path.join(self._repo.path, "MERGE_MSG")
        if not os.path.exists(merge_msg_path):
            return None
        with open(merge_msg_path) as f:
            return f.read()

    def has_unresolved_conflicts(self) -> bool:
        self._repo.index.read()
        if self._repo.index.conflicts is None:
            return False
        try:
            next(iter(self._repo.index.conflicts))
            return True
        except StopIteration:
            return False

    def get_identity(self) -> tuple[str | None, str | None]:
        """Return (user.name, user.email) from the merged git config.
        Either may be None if unset."""
        try:
            name = self._repo.config["user.name"]
        except KeyError:
            name = None
        try:
            email = self._repo.config["user.email"]
        except KeyError:
            email = None
        return name, email

    def set_identity(self, name: str, email: str, global_: bool) -> None:
        """Write user.name and user.email via subprocess `git config`.
        global_=True writes to ~/.gitconfig; False writes to this repo only."""
        import subprocess

        scope = "--global" if global_ else "--local"
        for key, value in (("user.name", name), ("user.email", email)):
            result = subprocess.run(
                ["git", "config", scope, key, value],
                cwd=self._repo.workdir or self._repo.path,
                env=self._git_env,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"git config {scope} {key} failed: "
                    f"{result.stderr.strip() or result.stdout.strip()}"
                )
