from __future__ import annotations

import threading
from collections.abc import Callable
from typing import NamedTuple

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox, QPushButton

from git_gui.presentation.bus import CommandBus, QueryBus


class _RemoteSignals(QObject):
    """Signal bridge — lives on main thread, emitted from background thread."""

    finished = Signal(str)
    failed = Signal(str, str)
    cancelled = Signal(str)


class _PushTarget(NamedTuple):
    """The remote branch a push wrote to: what a rejection offers to force."""

    remote: str
    branch: str


class RemoteOpQueueMixin:
    """Remote-operation serializer and queue.

    Provides `_run_remote_op` — a single-flight serializer that runs a
    callable on a background thread and marshals completion back to the
    main thread via Qt signals. Also hosts the push/pull/fetch slots.

    Mixin — not instantiable on its own. Relies on composite-provided
    attributes set up by MainWindow's __init__.
    """

    def _wire_remote_op_signals(self) -> None:
        self._graph.push_requested.connect(self._on_push)
        self._graph.pull_requested.connect(self._on_pull)
        self._graph.fetch_all_requested.connect(self._on_fetch_all_prune)
        self._sidebar.fetch_requested.connect(self._on_fetch_single)
        self._sidebar.tag_push_requested.connect(self._on_push_tag)
        self._sidebar.branch_push_requested.connect(self._on_push_branch)
        # Cancel button lives in the status bar, shown only while a remote op runs.
        self._cancel_remote_btn = QPushButton("✕ Cancel")
        self._cancel_remote_btn.setToolTip("Cancel the running push/pull/fetch")
        self._cancel_remote_btn.clicked.connect(self._cancel_remote_op)
        self._cancel_remote_btn.setVisible(False)
        self.statusBar().addPermanentWidget(self._cancel_remote_btn)
        self._remote_op_name: str | None = None
        # A repo switch replaces self._commands while the op runs, so what
        # follows up on the op must go to the repo it started in.
        self._remote_op_commands: CommandBus | None = None
        self._remote_op_push_target: _PushTarget | None = None

    def _run_remote_op(
        self,
        name: str,
        fn: Callable[[], object],
        *,
        commands: CommandBus | None = None,
        push_target: _PushTarget | None = None,
    ) -> None:
        """Run *fn* on a worker thread unless another remote op is running.

        *commands* is the bus *fn* works on, the active repo's unless given.
        *push_target* marks the op as a push that may be offered a force push.
        """
        if self._remote_running:
            self._report_remote_op_skipped(name)
            return

        self._log_panel.expand()
        self._log_panel.log(f"{name} — started...")
        self._remote_running = True
        self._remote_op_name = name
        self._remote_op_commands = commands if commands is not None else self._commands
        self._remote_op_push_target = push_target
        self.statusBar().showMessage(f"⏳ {name}...")
        self._cancel_remote_btn.setEnabled(True)
        self._cancel_remote_btn.setVisible(True)

        signals = _RemoteSignals()
        signals.finished.connect(self._on_remote_done)
        signals.failed.connect(self._on_remote_error)
        signals.cancelled.connect(self._on_remote_cancelled)
        self._remote_signals = signals  # prevent GC

        def _worker():
            try:
                fn()
                signals.finished.emit(name)
            except Exception as e:
                # Dispatch by class name to keep this layer infra-free (the
                # architecture guard forbids importing the concrete errors).
                if type(e).__name__ == "RemoteOperationCancelled":
                    signals.cancelled.emit(name)
                else:
                    signals.failed.emit(name, str(e))

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def _report_remote_op_skipped(self, name: str) -> None:
        """The user may already have confirmed *name*, so dropping it unannounced
        would leave them believing it ran."""
        running = self._remote_op_name or "another remote operation"
        self._log_panel.expand()
        self._log_panel.log_error(
            f"{name} — skipped: {running} is still running. Try again once it finishes."
        )

    def _cancel_remote_op(self) -> None:
        """Ask the running push/pull/fetch to abort by terminating its git
        subprocess. Completion is reported via the `cancelled` signal."""
        commands = self._remote_op_commands
        if not self._remote_running or commands is None:
            return
        self._log_panel.log(f"{self._remote_op_name or 'Remote operation'} — cancelling...")
        self._cancel_remote_btn.setEnabled(False)
        try:
            commands.cancel_remote_op.execute()
        except Exception as e:
            self._log_panel.log_error(f"Cancel — ERROR: {e}")

    def _end_remote_op(self) -> None:
        """Shared teardown for the done / error / cancelled outcomes."""
        self._remote_running = False
        self._remote_op_name = None
        self._remote_op_commands = None
        self._remote_op_push_target = None
        self.statusBar().clearMessage()
        self._cancel_remote_btn.setVisible(False)
        self._cancel_remote_btn.setEnabled(True)

    def _on_remote_done(self, name: str) -> None:
        self._log_panel.log(f"{name} — done")
        self._end_remote_op()
        self._reload()

    def _on_remote_cancelled(self, name: str) -> None:
        self._log_panel.log(f"{name} — cancelled")
        self._end_remote_op()
        self._reload()

    def _on_remote_error(self, name: str, error: str) -> None:
        commands, rejected = self._remote_op_commands, self._remote_op_push_target
        self._log_panel.log_error(f"{name} — ERROR: {error}")
        self._end_remote_op()
        self._reload()
        if commands is not None and rejected is not None and "non-fast-forward" in error:
            self._offer_force_push(commands, rejected)

    def _offer_force_push(self, commands: CommandBus, target: _PushTarget) -> None:
        remote_branch = f"{target.remote}/{target.branch}"
        reply = QMessageBox.warning(
            self,
            "Push Rejected",
            f"Push of '{target.branch}' was rejected because {remote_branch} has "
            "changes you don't have locally.\n\n"
            f"Would you like to force push '{target.branch}' with --force-with-lease?\n"
            f"This will overwrite {remote_branch}.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._run_remote_op(
                f"Force push {remote_branch}",
                lambda: commands.force_push.execute(target.remote, target.branch),
                commands=commands,
            )

    def _on_push(self) -> None:
        branch = self._get_current_branch()
        if branch:
            self._on_push_branch(branch)

    def _on_push_branch(self, branch: str) -> None:
        commands = self._commands
        target = _PushTarget("origin", branch)
        self._run_remote_op(
            f"Push {target.remote}/{target.branch}",
            lambda: commands.push.execute(target.remote, target.branch),
            commands=commands,
            push_target=target,
        )

    def _on_pull(self) -> None:
        branch = self._get_current_branch()
        if branch:
            self._run_remote_op(
                f"Pull origin/{branch}",
                lambda: self._commands.pull.execute("origin", branch),
            )

    def _on_fetch_all_prune(self) -> None:
        commands, queries, repo_path = self._commands, self._queries, self._repo_path

        def _fn():
            commands.fetch_all_prune.execute()
            self._update_remote_tag_cache(queries, repo_path, "origin")

        self._run_remote_op("Fetch --all --prune", _fn, commands=commands)

    def _on_fetch_single(self, remote: str) -> None:
        commands, queries, repo_path = self._commands, self._queries, self._repo_path

        def _fn():
            commands.fetch.execute(remote)
            self._update_remote_tag_cache(queries, repo_path, remote)

        self._run_remote_op(f"Fetch {remote}", _fn, commands=commands)

    def _on_push_tag(self, name: str) -> None:
        commands, queries, repo_path = self._commands, self._queries, self._repo_path

        def _fn():
            commands.push_tag.execute("origin", name)
            self._update_remote_tag_cache(queries, repo_path, "origin")

        self._run_remote_op(f"Push tag {name}", _fn, commands=commands)

    def _get_current_branch(self) -> str | None:
        if self._queries is None:
            return None
        branches = self._queries.get_branches.execute()
        for b in branches:
            if b.is_head and not b.is_remote:
                return b.name
        return None

    def _update_remote_tag_cache(
        self, queries: QueryBus | None, repo_path: str | None, remote: str
    ) -> None:
        """Runs on the worker thread, so it is handed the repo the op ran in:
        the active one may have been switched while the op ran."""
        if not self._remote_tag_cache or not repo_path or not queries:
            return
        try:
            remote_tags = queries.get_remote_tags.execute(remote)
            data = self._remote_tag_cache.load(repo_path)
            data[remote] = remote_tags
            self._remote_tag_cache.save(repo_path, data)
        except Exception:
            pass  # cache update failure is non-critical
