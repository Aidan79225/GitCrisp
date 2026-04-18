# git_gui/infrastructure/pygit2/merge_rebase_ops.py
from __future__ import annotations
import os
import subprocess

import pygit2

from git_gui.resources import subprocess_kwargs
from git_gui.domain.entities import MergeAnalysisResult, MergeStrategy


class MergeRebaseOps:
    """Merge, rebase, interactive rebase, abort/continue. Temp files +
    GIT_SEQUENCE_EDITOR / GIT_EDITOR env injection for interactive rebase.

    Mixin — not instantiable on its own. Relies on `self._repo` set up
    by the composite class.
    """
    _repo: pygit2.Repository  # provided by the composite

    def merge(self, branch: str, strategy: MergeStrategy = MergeStrategy.ALLOW_FF, message: str | None = None) -> None:
        if branch in self._repo.branches.local:
            ref = self._repo.branches.local[branch]
        else:
            ref = self._repo.branches.remote[branch]
        default_label = f"branch '{branch}'"
        self._merge_oid(ref.target, label=default_label, strategy=strategy, message=message)

    def merge_commit(self, oid: str, strategy: MergeStrategy = MergeStrategy.ALLOW_FF, message: str | None = None) -> None:
        target = pygit2.Oid(hex=oid)
        default_label = f"commit {oid[:7]}"
        self._merge_oid(target, label=default_label, strategy=strategy, message=message)

    def merge_analysis(self, oid: str) -> MergeAnalysisResult:
        target = pygit2.Oid(hex=oid)
        result, _ = self._repo.merge_analysis(target)
        can_ff = bool(result & pygit2.GIT_MERGE_ANALYSIS_FASTFORWARD)
        is_up_to_date = bool(result & pygit2.GIT_MERGE_ANALYSIS_UP_TO_DATE)
        return MergeAnalysisResult(can_ff=can_ff, is_up_to_date=is_up_to_date)

    def _merge_oid(self, target_oid, label: str, strategy: MergeStrategy = MergeStrategy.ALLOW_FF, message: str | None = None) -> None:
        merge_result, _ = self._repo.merge_analysis(target_oid)
        can_ff = bool(merge_result & pygit2.GIT_MERGE_ANALYSIS_FASTFORWARD)
        commit_message = message if message else f"Merge {label}"

        if strategy == MergeStrategy.FF_ONLY:
            if can_ff:
                self._repo.checkout_tree(self._repo.get(target_oid))
                self._repo.head.set_target(target_oid)
            else:
                raise RuntimeError("Cannot fast-forward this merge")
        elif strategy == MergeStrategy.NO_FF:
            self._repo.merge(target_oid)
            if not self._repo.index.conflicts:
                self._repo.index.write()
                tree = self._repo.index.write_tree()
                sig = self._get_signature()
                self._repo.create_commit(
                    "HEAD", sig, sig,
                    commit_message,
                    tree,
                    [self._repo.head.target, target_oid],
                )
                self._repo.state_cleanup()
        else:  # ALLOW_FF
            if can_ff:
                self._repo.checkout_tree(self._repo.get(target_oid))
                self._repo.head.set_target(target_oid)
            elif merge_result & pygit2.GIT_MERGE_ANALYSIS_NORMAL:
                self._repo.merge(target_oid)
                if not self._repo.index.conflicts:
                    self._repo.index.write()
                    tree = self._repo.index.write_tree()
                    sig = self._get_signature()
                    self._repo.create_commit(
                        "HEAD", sig, sig,
                        commit_message,
                        tree,
                        [self._repo.head.target, target_oid],
                    )
                    self._repo.state_cleanup()

    def rebase(self, branch: str) -> None:
        onto_ref = self._repo.branches.local[branch]
        self._rebase_onto(onto_ref.target)

    def rebase_onto_commit(self, oid: str) -> None:
        self._rebase_onto(pygit2.Oid(hex=oid))

    def merge_abort(self) -> None:
        self._run_git("merge", "--abort")

    def rebase_abort(self) -> None:
        self._run_git("rebase", "--abort")

    def rebase_continue(self, message: str = "") -> None:
        import sys, tempfile
        env = self._git_env
        if message:
            # Write the message to a temp file, then set GIT_EDITOR to a
            # command that copies it over the file git passes to the editor.
            msg_file = tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8",
            )
            msg_file.write(message)
            msg_file.close()
            # Use python to copy the temp file content into the editor target
            python = sys.executable.replace("\\", "/")
            msg_path = msg_file.name.replace("\\", "/")
            env["GIT_EDITOR"] = (
                f'{python} -c "'
                f"import shutil,sys; shutil.copy('{msg_path}', sys.argv[1])"
                f'"'
            )
        else:
            env["GIT_EDITOR"] = "true"
        try:
            result = subprocess.run(
                ["git", "rebase", "--continue"],
                cwd=self._repo.workdir, capture_output=True, text=True,
                env=env, **subprocess_kwargs(),
            )
            if result.returncode != 0:
                msg = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
                raise RuntimeError(msg)
        finally:
            if message:
                try:
                    os.unlink(msg_file.name)
                except OSError:
                    pass

    def interactive_rebase(self, target_oid: str, entries: list[tuple[str, str]]) -> None:
        """Run git rebase -i with a pre-built todo file.

        *entries* is a list of (action, oid) tuples in replay order.
        Actions: "pick", "squash", "fixup", "drop".
        """
        import sys
        import tempfile

        # Use the merge-base as the actual rebase target so git's internal
        # commit list matches the one we showed in the dialog. Without this,
        # git rebase -i <target_tip> might compute a different range than
        # get_commit_range() did.
        head_oid = str(self._repo.head.target)
        try:
            mb = self._repo.merge_base(head_oid, target_oid)
            rebase_target = str(mb)
        except Exception:
            rebase_target = target_oid

        # Build the todo file content
        todo_lines = [f"{action} {oid}" for action, oid in entries]
        todo_content = "\n".join(todo_lines) + "\n"

        # Write to a temp file
        todo_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8",
        )
        todo_file.write(todo_content)
        todo_file.close()

        env = self._git_env
        python = sys.executable.replace("\\", "/")
        todo_path = todo_file.name.replace("\\", "/")
        env["GIT_SEQUENCE_EDITOR"] = (
            f'{python} -c "'
            f"import shutil,sys; shutil.copy('{todo_path}', sys.argv[1])"
            f'"'
        )
        # Prevent interactive editor from opening for squash/fixup messages
        env["GIT_EDITOR"] = "true"

        try:
            result = subprocess.run(
                ["git", "rebase", "-i", rebase_target],
                cwd=self._repo.workdir, capture_output=True, text=True,
                env=env, **subprocess_kwargs(),
            )
            if result.returncode != 0:
                # Check if we're in a conflict state — let the banner handle it
                state = self._repo.state()
                rebase_states = set()
                for name in ("GIT_REPOSITORY_STATE_REBASE",
                             "GIT_REPOSITORY_STATE_REBASE_INTERACTIVE",
                             "GIT_REPOSITORY_STATE_REBASE_MERGE"):
                    const = getattr(pygit2, name, None)
                    if const is not None:
                        rebase_states.add(const)
                if state in rebase_states:
                    return  # conflict — Spec C banner will handle
                msg = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
                raise RuntimeError(msg)
        finally:
            try:
                os.unlink(todo_file.name)
            except OSError:
                pass

    def _rebase_onto(self, target_oid) -> None:
        # Convert Oid to hex string if needed
        target_hex = str(target_oid)
        self._run_git("rebase", target_hex)
