from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import NamedTuple

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox, QPushButton

from git_gui.domain.entities import TrackedBranch
from git_gui.domain.ports import RemoteOperationCancelled
from git_gui.presentation.bus import CommandBus, QueryBus

logger = logging.getLogger(__name__)

_RETRY_WHEN_FREE = "Try again once it finishes."


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
    """The remote-op slot: one push, pull or fetch at a time.

    `_run_remote_op` runs a callable on a background thread and marshals
    completion back to the main thread via Qt signals. A request made while
    another op holds the slot is reported as skipped and dropped, not queued.
    Also hosts the push, pull and fetch handlers.

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
        if self._remote_slot_busy(name):
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
            except RemoteOperationCancelled:
                signals.cancelled.emit(name)
            except Exception as e:
                signals.failed.emit(name, str(e))

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def _remote_slot_busy(self, name: str, *, retry_hint: str = _RETRY_WHEN_FREE) -> bool:
        """Whether another remote op holds the slot, logging *name* as skipped if so.

        An op that asks the user first calls this before asking, so that what
        they confirm is never dropped.
        """
        if self._remote_running:
            self._report_remote_op_skipped(name, retry_hint)
        return self._remote_running

    def _report_remote_op_skipped(self, name: str, retry_hint: str = _RETRY_WHEN_FREE) -> None:
        """The user may already have confirmed *name*, so dropping it unannounced
        would leave them believing it ran."""
        running = self._remote_op_name or "another remote operation"
        self._log_panel.expand()
        self._log_panel.log_error(f"{name} — skipped: {running} is still running. {retry_hint}")

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
        branch = self._branch_to_sync("Push")
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
        branch = self._branch_to_sync("Pull")
        if branch is None:
            return
        commands = self._commands
        source = self._pull_source(branch)
        label = source.branch if source.is_local else f"{source.remote}/{source.branch}"
        self._run_remote_op(
            f"Pull {label}",
            lambda: commands.pull.execute(source.remote, source.ref),
            commands=commands,
        )

    def _pull_source(self, branch: str) -> TrackedBranch:
        """What `git pull` takes *branch* from: what the branch tracks, else
        the same-named branch on origin.

        Only what it tracks can say whether that is a local branch (one
        branch stacked on another, pulled from this repo) or a remote's:
        the upstream's shorthand reads "origin/main" for both a local branch
        of that name and origin's main. The full ref goes to git so that it
        need not guess between them either.
        """
        tracked = self._tracked_by(branch)
        return tracked if tracked is not None else TrackedBranch("origin", f"refs/heads/{branch}")

    def _tracked_by(self, branch: str) -> TrackedBranch | None:
        try:
            infos = self._queries.list_local_branches_with_upstream.execute()
        except Exception as e:
            logger.warning("Reading what %r tracks failed: %s", branch, e)
            return None
        return next((info.tracks for info in infos if info.name == branch), None)

    def _remote_names(self) -> list[str]:
        """The repo's remotes, or none (reported) when they cannot be listed:
        a single remote with an invalid name in .git/config fails the whole
        listing."""
        try:
            return [r.name for r in self._queries.list_remotes.execute()]
        except Exception as e:
            logger.warning("Listing remotes failed for %s: %s", self._repo_path, e)
            self._log_panel.log_error(f"Listing remotes failed: {e}")
            return []

    def _branch_to_sync(self, op: str) -> str | None:
        """The checked-out branch, or None after logging that HEAD is on none.

        The toolbar's Push and Pull stay enabled on a detached HEAD (every
        rebase stops on one) and in a repo with no commits yet, so a click
        there needs an answer.
        """
        if self._queries is None:
            return None
        branch = self._get_current_branch()
        if branch is None:
            self._log_panel.expand()
            self._log_panel.log_error(
                f"{op} — HEAD is not on a branch (detached, or no commits yet). "
                "Check out a branch first."
            )
        return branch

    def _on_fetch_all_prune(self) -> None:
        self._run_then_refresh_tags(
            "Fetch --all --prune", lambda commands: commands.fetch_all_prune.execute(), "origin"
        )

    def _on_fetch_single(self, remote: str) -> None:
        self._run_then_refresh_tags(
            f"Fetch {remote}", lambda commands: commands.fetch.execute(remote), remote
        )

    def _on_push_tag(self, name: str) -> None:
        self._run_then_refresh_tags(
            f"Push tag {name}", lambda commands: commands.push_tag.execute("origin", name), "origin"
        )

    def _run_then_refresh_tags(
        self, name: str, run: Callable[[CommandBus], object], remote: str
    ) -> None:
        """Run an op that changes *remote*'s tags, then re-read them into the
        tag cache, both in the repo the op was started in."""
        commands, queries, repo_path = self._commands, self._queries, self._repo_path

        def _fn() -> None:
            run(commands)
            self._update_remote_tag_cache(queries, repo_path, remote)

        self._run_remote_op(name, _fn, commands=commands)

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
