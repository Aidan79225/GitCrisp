from __future__ import annotations
import os

import pygit2

from git_gui.domain.entities import RepoState, RepoStateInfo


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
        """
        env = os.environ.copy()
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
        state = self._repo.state()
        raw_map = {
            "GIT_REPOSITORY_STATE_NONE": RepoState.CLEAN,
            "GIT_REPOSITORY_STATE_MERGE": RepoState.MERGING,
            "GIT_REPOSITORY_STATE_REVERT": RepoState.REVERTING,
            "GIT_REPOSITORY_STATE_CHERRYPICK": RepoState.CHERRY_PICKING,
            "GIT_REPOSITORY_STATE_REBASE": RepoState.REBASING,
            "GIT_REPOSITORY_STATE_REBASE_INTERACTIVE": RepoState.REBASING,
            "GIT_REPOSITORY_STATE_REBASE_MERGE": RepoState.REBASING,
            "GIT_REPOSITORY_STATE_APPLY_MAILBOX": RepoState.CLEAN,
            "GIT_REPOSITORY_STATE_APPLY_MAILBOX_OR_REBASE": RepoState.REBASING,
        }
        state_map: dict[int, RepoState] = {}
        for name, mapped_state in raw_map.items():
            const = getattr(pygit2, name, None)
            if const is not None:
                state_map[const] = mapped_state
        mapped = state_map.get(state, RepoState.CLEAN)

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
