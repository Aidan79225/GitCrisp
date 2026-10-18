from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

import pygit2

from git_gui.domain.entities import MergeAnalysisResult, MergeStrategy, RebaseTodoEntry
from git_gui.infrastructure.git_process import run_git
from git_gui.infrastructure.pygit2.repo_state_ops import REBASE_STATES


def _editor_copying(source_path: str) -> str:
    """A GIT_EDITOR / GIT_SEQUENCE_EDITOR command that replaces the file git
    hands the editor with the contents of *source_path*.

    git runs the editor through its own sh (bundled with Git for Windows), so
    ``cp`` is always there. A Python interpreter is not: in the frozen release
    ``sys.executable`` is GitCrisp itself.
    """
    return "cp " + shlex.quote(Path(source_path).as_posix())


@contextmanager
def _file_holding(text: str) -> Iterator[str]:
    """Yield the path of a temp file holding *text*; the file is removed on exit.

    It is closed before the path is yielded: on Windows the editor command
    could not read a file this process still holds open.
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(text)
    try:
        yield handle.name
    finally:
        with suppress(OSError):
            os.unlink(handle.name)


def _failure_message(result: subprocess.CompletedProcess[str]) -> str:
    return result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"


class MergeRebaseOps:
    """Merge, rebase, interactive rebase, abort/continue. Temp files +
    GIT_SEQUENCE_EDITOR / GIT_EDITOR env injection for interactive rebase.

    Mixin — not instantiable on its own. Relies on `self._repo` set up
    by the composite class.
    """

    _repo: pygit2.Repository  # provided by the composite

    def merge(
        self,
        branch: str,
        strategy: MergeStrategy = MergeStrategy.ALLOW_FF,
        message: str | None = None,
    ) -> None:
        if branch in self._repo.branches.local:
            ref = self._repo.branches.local[branch]
        else:
            ref = self._repo.branches.remote[branch]
        default_label = f"branch '{branch}'"
        self._merge_oid(ref.target, label=default_label, strategy=strategy, message=message)

    def merge_commit(
        self, oid: str, strategy: MergeStrategy = MergeStrategy.ALLOW_FF, message: str | None = None
    ) -> None:
        target = pygit2.Oid(hex=oid)
        default_label = f"commit {oid[:7]}"
        self._merge_oid(target, label=default_label, strategy=strategy, message=message)

    def merge_analysis(self, oid: str) -> MergeAnalysisResult:
        target = pygit2.Oid(hex=oid)
        result, _ = self._repo.merge_analysis(target)
        can_ff = bool(result & pygit2.GIT_MERGE_ANALYSIS_FASTFORWARD)
        is_up_to_date = bool(result & pygit2.GIT_MERGE_ANALYSIS_UP_TO_DATE)
        return MergeAnalysisResult(can_ff=can_ff, is_up_to_date=is_up_to_date)

    def _merge_oid(
        self,
        target_oid,
        label: str,
        strategy: MergeStrategy = MergeStrategy.ALLOW_FF,
        message: str | None = None,
    ) -> None:
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
            self._merge_into_head(target_oid, commit_message)
        else:  # ALLOW_FF
            if can_ff:
                self._repo.checkout_tree(self._repo.get(target_oid))
                self._repo.head.set_target(target_oid)
            elif merge_result & pygit2.GIT_MERGE_ANALYSIS_NORMAL:
                self._merge_into_head(target_oid, commit_message)

    def _merge_into_head(self, target_oid, commit_message: str) -> None:
        """Create the merge commit, or on conflict leave the merge in progress
        with *commit_message* waiting in MERGE_MSG for the conflict banner."""
        self._repo.merge(target_oid)
        if self._repo.index.conflicts:
            self._write_merge_msg(commit_message)
            return
        self._repo.index.write()
        tree = self._repo.index.write_tree()
        sig = self._get_signature()
        self._repo.create_commit(
            "HEAD",
            sig,
            sig,
            commit_message,
            tree,
            [self._repo.head.target, target_oid],
        )
        self._repo.state_cleanup()

    def _write_merge_msg(self, commit_message: str) -> None:
        # libgit2 leaves "Merge commit '<sha>'" plus "#Conflicts:" lines here,
        # and the app commits MERGE_MSG verbatim: unlike git's editor, nothing
        # strips comment lines afterwards.
        merge_msg = Path(self._repo.path, "MERGE_MSG")
        merge_msg.write_text(commit_message + "\n", encoding="utf-8", newline="")

    def rebase(self, branch: str) -> None:
        if branch in self._repo.branches.local:
            onto_ref = self._repo.branches.local[branch]
        else:
            onto_ref = self._repo.branches.remote[branch]
        self._rebase_onto(onto_ref.target)

    def rebase_onto_commit(self, oid: str) -> None:
        self._rebase_onto(pygit2.Oid(hex=oid))

    def merge_abort(self) -> None:
        self._run_git("merge", "--abort")

    def rebase_abort(self) -> None:
        self._run_git("rebase", "--abort")

    def rebase_continue(self, message: str = "") -> None:
        if not message:
            self._continue_rebase(editor="true")
            return
        with _file_holding(message) as message_path:
            self._continue_rebase(editor=_editor_copying(message_path))

    def _continue_rebase(self, editor: str) -> None:
        env = {**self._git_env, "GIT_EDITOR": editor}
        result = run_git(["git", "rebase", "--continue"], cwd=self._repo.workdir, env=env)
        if result.returncode != 0:
            raise RuntimeError(_failure_message(result))

    def interactive_rebase(self, target_oid: str, entries: list[RebaseTodoEntry]) -> None:
        """Run git rebase -i with *entries*, in replay order, as its todo list.

        The todo file replaces the list git computes, so git replays exactly
        *entries* onto *target_oid*, whatever range it would have picked. That
        includes a commit whose patch the target already has, which git would
        have left out; ``--empty=drop`` drops it when it comes out empty
        instead of stopping as if on a conflict.
        """
        todo = "\n".join(f"{action} {oid}" for action, oid in entries) + "\n"
        with _file_holding(todo) as todo_path:
            env = {
                **self._git_env,
                "GIT_SEQUENCE_EDITOR": _editor_copying(todo_path),
                # Takes the message git proposes for a squash; there is no
                # editor a GUI user could answer.
                "GIT_EDITOR": "true",
            }
            result = run_git(
                ["git", "rebase", "-i", "--empty=drop", target_oid],
                cwd=self._repo.workdir,
                env=env,
            )
        # A stopped rebase is a conflict, not a failure — leave the repo as it
        # is and let the conflict banner drive it from here.
        if result.returncode != 0 and self._repo.state() not in REBASE_STATES:
            raise RuntimeError(_failure_message(result))

    def _rebase_onto(self, target_oid) -> None:
        target_hex = str(target_oid)
        self._run_git("rebase", target_hex)
