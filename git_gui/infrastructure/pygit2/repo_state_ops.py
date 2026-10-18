from __future__ import annotations

import os
from typing import NamedTuple

import pygit2

from git_gui.domain.entities import RepoState, RepoStateInfo
from git_gui.infrastructure.git_process import run_git
from git_gui.resources import GitConfig, git_ssh_env

_SSH_COMMAND_KEY = "core.sshCommand"


class _SshCommandAnswer(NamedTuple):
    remote_urls: tuple[str, ...]
    is_set: bool


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

# The states that mean "a rebase is in progress", derived from the table above
# so the two can never disagree. Callers that only need the yes/no answer take
# this rather than re-listing constants of their own — doing that by name, with
# `getattr(pygit2, name, None)`, is what broke silently in 1.20.
REBASE_STATES = frozenset(
    state for state, mapped in _REPO_STATE_MAP.items() if mapped is RepoState.REBASING
)


class RepoStateOps:
    """Repository-level state reads (HEAD, state, MERGE_HEAD) and the
    `_git_env` property that other mixins' subprocess calls rely on.

    Mixin — not instantiable on its own. Relies on `self._repo` set up
    by the composite class.
    """

    _repo: pygit2.Repository  # provided by the composite
    _ssh_command_answer: _SshCommandAnswer | None = None

    @property
    def _git_env(self) -> dict:
        """Environment dict forcing git CLI to use this repo's gitdir/worktree.

        Without this, ``subprocess.run(["git", ...], cwd=workdir)`` lets git
        walk up looking for ``.git`` — which for a submodule workdir that
        has no ``.git`` file lands on the *parent* repo and runs the command
        against the wrong remote.

        Also carries ``GIT_SSH_COMMAND`` so remote ops (push/pull/fetch) don't
        fail on first-time SSH host-key verification, unless this repo's
        config, which includes the user's global one, names an ssh command.
        """
        env = os.environ.copy()
        env["GIT_DIR"] = self._repo.path
        if self._repo.workdir:
            env["GIT_WORK_TREE"] = self._repo.workdir
        return git_ssh_env(env, config=self._ssh_config(env))

    def _ssh_config(self, env: dict[str, str]) -> GitConfig:
        """The config that says whether the user named an ssh command.

        libgit2 does not evaluate ``includeIf "hasconfig:remote.*.url:..."``
        (git 2.36+), the usual way to give a second account its own
        ``core.sshCommand``, so only git itself can say such a key is set.
        Asking it costs a process on every git call, the auto-reload's dirty
        check among them, so its answer is kept until the remote URLs that
        such an include matches on change.
        """
        if _SSH_COMMAND_KEY in self._repo.config:
            return self._repo.config
        remote_urls = tuple(remote.url or "" for remote in self._repo.remotes)
        answer = self._ssh_command_answer
        if answer is None or answer.remote_urls != remote_urls:
            answer = _SshCommandAnswer(remote_urls, self._git_resolves(_SSH_COMMAND_KEY, env))
            self._ssh_command_answer = answer
        return frozenset({_SSH_COMMAND_KEY}) if answer.is_set else frozenset()

    def _git_resolves(self, key: str, env: dict[str, str]) -> bool:
        result = run_git(
            ["git", "config", "--get", key], cwd=self._repo.workdir or self._repo.path, env=env
        )
        return result.returncode == 0

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
        # git writes it as UTF-8; without an explicit encoding Windows decodes
        # with the ANSI code page and a non-ASCII conflicted path raises.
        with open(merge_msg_path, encoding="utf-8", errors="replace") as f:
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
        scope = "--global" if global_ else "--local"
        for key, value in (("user.name", name), ("user.email", email)):
            result = run_git(
                ["git", "config", scope, key, value],
                cwd=self._repo.workdir or self._repo.path,
                env=self._git_env,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"git config {scope} {key} failed: "
                    f"{result.stderr.strip() or result.stdout.strip()}"
                )
