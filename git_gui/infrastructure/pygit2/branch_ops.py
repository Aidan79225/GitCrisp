from __future__ import annotations

import logging

import pygit2

from git_gui.domain.entities import Branch, LocalBranchInfo

logger = logging.getLogger(__name__)


class BranchOps:
    """Branch read and write operations for the pygit2 adapter.

    Mixin — not instantiable on its own. Relies on `self._repo` set up
    by the composite class.
    """

    _repo: pygit2.Repository  # provided by the composite

    # ── METHODS COPIED VERBATIM from Pygit2Repository ─────────────────
    def get_branches(self) -> list[Branch]:
        branches: list[Branch] = []
        # Compare HEAD's ref name (e.g. "refs/heads/main"), not target oid,
        # so only the actual checked-out branch is marked as head.
        try:
            head_ref_name = self._repo.head.name if not self._repo.head_is_unborn else None
        except Exception as e:
            logger.warning("Failed to read HEAD ref name: %s", e)
            head_ref_name = None

        for name in self._repo.branches.local:
            ref = self._repo.branches.local[name]
            branches.append(
                Branch(
                    name=name,
                    is_remote=False,
                    is_head=(ref.name == head_ref_name),
                    target_oid=str(ref.resolve().target),
                )
            )
        for name in self._repo.branches.remote:
            ref = self._repo.branches.remote[name]
            branches.append(
                Branch(
                    name=name,
                    is_remote=True,
                    is_head=False,
                    target_oid=str(ref.target),
                )
            )
        return branches

    def list_local_branches_with_upstream(self) -> list[LocalBranchInfo]:
        result: list[LocalBranchInfo] = []
        for name in self._repo.branches.local:
            br = self._repo.branches.local[name]
            try:
                upstream = br.upstream.shorthand if br.upstream else None
            except Exception as e:
                logger.warning("Failed to read upstream for branch %r: %s", name, e)
                upstream = None
            commit = br.peel(pygit2.Commit)
            sha = str(commit.id)[:10]
            msg = commit.message.strip().split("\n", 1)[0]
            result.append(
                LocalBranchInfo(
                    name=name,
                    upstream=upstream,
                    last_commit_sha=sha,
                    last_commit_message=msg,
                )
            )
        return result

    def create_branch(self, name: str, from_oid: str) -> Branch:
        commit = self._repo.get(from_oid)
        self._repo.create_branch(name, commit, False)
        return Branch(name=name, is_remote=False, is_head=False, target_oid=from_oid)

    def _refresh_index(self) -> None:
        """Reload the in-memory index from disk before a checkout.

        pygit2 caches the index on ``self._repo``. Subprocess git operations
        (merge/rebase/cherry-pick abort & continue, and any command the user
        runs in a terminal) mutate ``.git/index`` on disk without touching the
        cached object. A checkout consults the cached index, so a stale one
        still holding conflict entries makes pygit2 raise "unresolved conflicts
        exist in the index" even though the repository on disk is clean.

        Re-reading from disk is safe: staging always writes the index
        immediately, so there are never in-memory-only changes to lose.
        """
        self._repo.index.read()

    def checkout(self, branch: str) -> None:
        self._refresh_index()
        ref = self._repo.branches.local[branch]
        self._repo.checkout(ref)

    def checkout_commit(self, oid: str) -> None:
        self._refresh_index()
        commit = self._repo.get(oid)
        self._repo.checkout_tree(commit)
        self._repo.set_head(commit.id)

    def checkout_remote_branch(self, remote_branch: str) -> None:
        self._refresh_index()
        # "origin/feature" → local branch "feature" tracking "origin/feature"
        parts = remote_branch.split("/", 1)
        local_name = parts[1] if len(parts) > 1 else remote_branch
        remote_ref = self._repo.branches.remote[remote_branch]
        # Create local branch at the same commit
        local_ref = self._repo.branches.local.create(local_name, self._repo.get(remote_ref.target))
        local_ref.upstream = remote_ref
        self._repo.checkout(local_ref)

    def delete_branch(self, name: str) -> None:
        self._repo.branches.local[name].delete()

    def delete_remote_branch(self, remote: str, branch: str) -> None:
        """Delete a branch on the remote via `git push <remote> --delete <branch>`."""
        self._run_git("push", remote, "--delete", branch)

    def rename_branch(self, old_name: str, new_name: str) -> None:
        self._repo.branches.local[old_name].rename(new_name)

    def set_branch_upstream(self, name: str, upstream: str) -> None:
        local = self._repo.branches.local[name]
        remote = self._repo.branches.remote[upstream]
        local.upstream = remote

    def unset_branch_upstream(self, name: str) -> None:
        local = self._repo.branches.local[name]
        local.upstream = None

    def reset_branch_to_ref(self, branch: str, ref: str) -> None:
        target = self._repo.revparse_single(ref)
        oid = target.id if hasattr(target, "id") else target.target
        self._repo.reset(oid, pygit2.GIT_RESET_HARD)
