from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from git_gui.domain.entities import Worktree
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.main_window.asked_repo_guard import AskedRepoGuardMixin
from git_gui.presentation.menus.git_menu import install_git_menu
from git_gui.presentation.paths import same_path_text
from git_gui.presentation.services.repo_change_detector import RepoChangeDetector


class _RepoReadySignals(QObject):
    ready = Signal(object, object, object)  # the _RepoRequest, QueryBus, CommandBus
    failed = Signal(object, str)  # the _RepoRequest, error


class _SwitchReason(Enum):
    """What a requested repo does to the repo store once it has opened.

    Nothing is recorded before then: a path that fails to open must not end
    up listed as open, or as active, while another repo is on screen.
    """

    SWITCH = auto()  # becomes the active repo; the open list is left alone
    OPEN = auto()  # joins the open list
    REPLACE = auto()  # succeeds a repo just closed; failing leaves nothing to show


@dataclass(frozen=True)
class _RepoRequest:
    path: str
    reason: _SwitchReason = _SwitchReason.SWITCH
    after: str | None = None  # the open repo an OPEN is listed after; None lists it first
    # Set once a closed repo hands over to this request: the open repo to go
    # to instead if it fails, as closing would have without it. None when no
    # other repo is open.
    fallback: str | None = None
    # Which open answers this request. Two attempts at one path, a row clicked
    # again or a repeating Ctrl+<n>, finish on their threads in any order, so
    # the path cannot tell their answers apart. replace() keeps it: a request
    # a close hands over to is still waiting for the same open.
    attempt: object = field(default_factory=object, compare=False, repr=False)


def _replaces_a_closed_repo(request: _RepoRequest) -> bool:
    return request.reason is _SwitchReason.REPLACE or request.fallback is not None


def _branches_in_use(worktrees: list[Worktree]) -> dict[str, str]:
    """Branch -> the worktree it is checked out in.

    The main worktree counts too: git refuses a branch checked out in any
    worktree, not only in a linked one.
    """
    return {wt.branch: str(wt.path) for wt in worktrees if wt.branch}


def _worktree_root(path: str, worktrees: list[Worktree]) -> str:
    """The worktree *path* is in, as *worktrees* name it.

    Open Repository accepts any folder inside a repository, and the window
    keeps the one it was given. The deepest worktree wins: a linked worktree
    can sit inside the main one's folder. *path* is the open repo's, so
    resolving it reaches no share that may be down.
    """
    opened = Path(path).resolve()
    roots = [Path(wt.path) for wt in worktrees if opened.is_relative_to(wt.path)]
    return str(max(roots, key=lambda root: len(root.parts), default=path))


def _close_open_menus() -> None:
    """Close every open menu, the parents of an open submenu included.

    A menu runs a nested event loop, so a switch already on its way lands
    while one is up, and its entries name a row of the repo on screen when it
    opened: a stash number, a branch, a file. Picked after the switch, they
    ran against the repo that replaced it. A closed menu returns no entry and
    fires none. Closing a submenu leaves its parent the active popup.
    """
    popup = QApplication.activePopupWidget()
    while popup is not None:
        popup.close()
        following = QApplication.activePopupWidget()
        if following is popup:
            return  # it would not close: asking it again would never end
        popup = following


class _WorktreeOpSignals(QObject):
    done = Signal(object)  # what the command returned
    failed = Signal(object)  # the exception it raised


class RepoLifecycleMixin(AskedRepoGuardMixin):
    """Repo lifecycle — switching, opening, closing, empty-state, recents.

    Mixin — not instantiable on its own. Relies on composite-provided
    attributes (self._queries, self._commands, self._repo_path, self._repo_store,
    self._session_factory, widget refs, ...) set up by MainWindow's __init__.
    """

    def _wire_repo_lifecycle_signals(self) -> None:
        # Not the store's active repo: one that would not open at launch is
        # kept active there, with nothing on screen.
        self._repo_list.show_open_repo_from(lambda: self._repo_path)
        self._repo_list.repo_switch_requested.connect(self._switch_repo)
        self._repo_list.repo_open_requested.connect(self._on_repo_open)
        self._repo_list.repo_close_requested.connect(self._on_repo_close)
        self._repo_list.repo_remove_recent_requested.connect(self._on_repo_remove_recent)
        self._repo_list.worktree_action_requested.connect(self._on_worktree_action)
        self._repo_list.save_failed.connect(self._report_unsaved_repo_list)
        self._repo_ready_signals.ready.connect(self._on_repo_ready)
        self._repo_ready_signals.failed.connect(self._on_repo_failed)

        # Bridge branch -> "Checkout in New Worktree…" requests from the
        # sidebar and graph context menus to the Add Worktree dialog. Bound
        # once: the widgets live for the app's lifetime and the handler reads
        # the active repo when it runs, so there is nothing repo-specific to
        # rebind. It used to be re-bound on every repo switch, which meant
        # disconnecting a signal that had nothing connected on the first pass —
        # Qt warns rather than raising, so the `except` around it never caught
        # anything and every run printed the warning.
        for owner in (self._sidebar, self._graph):
            owner.checkout_in_new_worktree_requested.connect(
                lambda branch: self._open_add_worktree_dialog(
                    preselect_branch=branch, default_create=False
                )
            )

    def _install_git_menu(self) -> None:
        """(Re)build the Git menu for whatever repo is open now.

        One call site for the arguments. There used to be three, and they had
        already drifted: the one that runs at startup never passed the
        worktrees callback, so `Git → Worktrees…` did nothing until the user
        switched repos.
        """
        # The Branches dialog lists this install's repo, and a switch can land
        # while it is up: a branch picked there must not go to the repo that opened.
        asked_in = self._commands

        def _checkout(branch: str) -> None:
            if not self._repo_switched_while_asking(asked_in, f"Checkout {branch}"):
                self._on_checkout_branch(branch)

        def _checkout_in_new_worktree(branch: str) -> None:
            op_name = f"Checkout {branch} in a new worktree"
            if not self._repo_switched_while_asking(asked_in, op_name):
                self._open_add_worktree_dialog(preselect_branch=branch, default_create=False)

        install_git_menu(
            self,
            queries=self._queries,
            commands=self._commands,
            repo_workdir=self._repo_path,
            on_open_submodule=self._on_submodule_open_requested,
            on_open_worktrees_dialog=self._open_worktrees_dialog,
            on_open_reflog=self.open_reflog,
            on_checkout_branch=_checkout,
            on_checkout_in_new_worktree=_checkout_in_new_worktree,
            worktree_paths=lambda: self._worktree_paths_by_branch,
        )

    def _start_change_detector(self, path: str) -> None:
        """Watch *path* for changes made outside GitCrisp, replacing any
        previous watch.

        Called from MainWindow's __init__ as well as from a repo switch. It
        used to be inline in the switch handler alone, which meant a window
        opened straight onto a repo — the ordinary way to start the app — had
        no detector at all, and noticed nothing until the user happened to
        switch repos.
        """
        self._stop_change_detector()
        self._change_detector = RepoChangeDetector(
            repo_path=path,
            on_reload=self._reload,
            parent=self,
        )

    def _stop_change_detector(self) -> None:
        """Stop and release the current change detector, if any."""
        if self._change_detector is not None:
            self._change_detector.stop()
            self._change_detector.deleteLater()
            self._change_detector = None

    def _switch_repo(self, path: str) -> None:
        self._request_repo(_RepoRequest(path))

    def _request_repo(self, request: _RepoRequest) -> None:
        # Each open runs on its own thread, and they finish in any order — one
        # on a network share can take seconds — so only the latest may land.
        self._repo_request = request
        signals = self._repo_ready_signals

        def _worker():
            try:
                queries, commands = self._session_factory(request.path)
                signals.ready.emit(request, queries, commands)
            except Exception as e:
                signals.failed.emit(request, str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _request_answered_by(self, opened: _RepoRequest) -> _RepoRequest | None:
        """The request waiting for *opened*'s open, or None if a later one
        replaced it, an earlier attempt at the same path included."""
        request = self._repo_request
        return request if request is not None and request.attempt is opened.attempt else None

    def _on_repo_ready(self, opened: _RepoRequest, queries: QueryBus, commands: CommandBus) -> None:
        request = self._request_answered_by(opened)
        if request is None:
            return  # superseded: the user has asked for something else since
        path = request.path
        _close_open_menus()
        # Both panes show the repo being left behind.
        self._close_blame_pane()
        self._close_reflog_pane()
        if path != self._repo_path:
            self._forget_undoable()
        self._queries = queries
        self._commands = commands
        self._repo_path = path
        # set_repo_path BEFORE set_buses — set_buses immediately triggers
        # sidebar.reload() which captures _repo_path in a worker thread for the
        # remote-tag cache lookup. If we set it after, the worker reads the
        # previous repo's cache and the tag synced markers disappear.
        self._sidebar.set_repo_path(path)
        self._sidebar.set_buses(self._queries, self._commands)
        self._graph.set_repo_path(path)
        self._graph.set_buses(self._queries, self._commands)
        self._diff.set_buses(self._queries, self._commands)
        self._working_tree.set_repo_path(path)
        self._working_tree.set_buses(self._queries, self._commands)
        self._record_in_store(request)
        self.save_repo_list()
        self._repo_list.reload()
        self.setWindowTitle(f"GitCrisp — {path}")
        # Re-install the Git menu so its actions bind to the new repo.
        self._install_git_menu()
        self._right_stack.setCurrentIndex(0)

        self._start_change_detector(path)

        # Load worktree list, paint badges/sidebar entries, refresh repo list.
        self._load_worktrees_for_active_repo()
        self._refresh_state_banners()

    def save_repo_list(self) -> None:
        """Write the repo list out, reporting a failed write rather than raising.

        The in-memory store is already right. An OSError escaping a slot — a
        file briefly locked by antivirus or a sync client, a full disk — would
        abandon a switch or a close halfway, with the panes on one repo and the
        title, Git menu and change detector still on the other. Escaping the
        launch, it stopped GitCrisp before the window showed.
        """
        try:
            self._repo_store.save()
        except OSError as e:
            self._report_unsaved_repo_list(str(e))

    def reload_repo_list(self) -> None:
        """Redraw the repo list from the store, which something other than the
        window has changed since the list was drawn."""
        self._repo_list.reload()

    def _report_unsaved_repo_list(self, reason: str) -> None:
        self._log_panel.expand()
        self._log_panel.log_error(f"Could not save the repo list: {reason}")

    def _record_in_store(self, request: _RepoRequest) -> None:
        if request.reason is _SwitchReason.OPEN:
            self._repo_store.add_open(request.path, after=request.after)
        else:
            self._repo_store.set_active(request.path)

    def _on_repo_failed(self, opened: _RepoRequest, error: str) -> None:
        self._log_panel.expand()
        self._log_panel.log_error(f"Cannot open {opened.path}: {error}")
        request = self._request_answered_by(opened)
        if request is None:
            return  # superseded: the user has asked for something else since
        if request.fallback in self._repo_store.get_open_repos():
            # It was taking over from a repo closed while it opened: go where
            # that close would have gone without it.
            self._request_repo(_RepoRequest(request.fallback, _SwitchReason.REPLACE))
        elif request.reason is _SwitchReason.REPLACE:
            # The repo on screen is already closed. Staying on it would leave
            # Ctrl+W retrying this one forever.
            self._enter_empty_state()
        else:
            # The window stays where it was, empty if a close handed over to
            # this request. Left pending, the failed request would be what
            # Ctrl+W hands over to, and it never lands.
            self._stop_waiting_for_request()

    def _stop_waiting_for_request(self) -> None:
        """Count nothing as on its way: the repo on screen is the latest request."""
        self._repo_request = _RepoRequest(self._repo_path) if self._repo_path else None

    def _enter_empty_state(self) -> None:
        self._repo_request = None
        self._clear_window()

    def _clear_window(self) -> None:
        """Show no repo, leaving any requested one free to land when it opens."""
        _close_open_menus()
        self._stop_change_detector()
        self._close_blame_pane()
        self._close_reflog_pane()
        self._forget_undoable()
        self._queries = None
        self._commands = None
        self._repo_path = None
        self._worktree_paths_by_branch = {}
        self._sidebar.set_repo_path(None)
        self._sidebar.set_buses(None, None)
        self._sidebar.set_worktree_branches(set())
        self._graph.set_repo_path(None)
        self._graph.set_buses(None, None)
        self._diff.set_buses(None, None)
        self._working_tree.set_repo_path(None)
        self._working_tree.set_buses(None, None)
        self._right_stack.setCurrentIndex(0)
        self._repo_list.set_active_worktrees([])
        self._repo_list.reload()
        self.setWindowTitle("GitCrisp")
        self._install_git_menu()

    def _on_repo_open(self, path: str, after: str | None = None) -> None:
        self._request_repo(_RepoRequest(path, _SwitchReason.OPEN, after=after))

    def _on_repo_close(self, path: str) -> None:
        on_screen = self._closing_takes_what_is_on_screen(path)
        # The repo on its way is never its own fallback: retrying it when it
        # fails would wait out the same dead share a second time.
        pending = self._pending_request()
        successor = self._repo_after_closing(path, skipping=pending.path if pending else None)
        self._repo_store.close_repo(path)
        if on_screen and self._repo_store.get_active() == self._repo_path:
            # The linked worktree of *path* on screen goes with it. Whatever
            # lands next records itself; if nothing does, the next launch
            # must not open onto a worktree whose repo is closed.
            self._repo_store.clear_active()
        self.save_repo_list()
        self._drop_pending_request_for(path)
        if not on_screen:
            self._repo_list.reload()  # some other row: stay where you are
        elif (pending := self._pending_request()) is not None:
            # The repo already on its way takes over.
            self._repo_request = replace(pending, fallback=successor)
            self._clear_window()
        elif successor is None:
            self._enter_empty_state()
        else:
            self._request_repo(_RepoRequest(successor, _SwitchReason.REPLACE))

    def _closing_takes_what_is_on_screen(self, path: str) -> bool:
        """Whether *path* is the repo on screen, the repo on its way to replace
        it after it was closed, or the open repo whose linked worktree is on
        screen — that worktree's only row hangs under it.

        A repo a close handed over to replaces the closed one too, though the
        user asked for it as a switch: it carries the fallback.
        """
        if path == self._repo_path:
            return True
        pending = self._pending_request()
        if pending is not None and pending.path == path and _replaces_a_closed_repo(pending):
            return True
        in_owned_worktree = self._repo_path not in self._repo_store.get_open_repos()
        return in_owned_worktree and path == self._repo_list.worktree_owner()

    def _pending_request(self) -> _RepoRequest | None:
        """The request still opening, or None once the latest one has landed."""
        request = self._repo_request
        return request if request is not None and request.path != self._repo_path else None

    def _drop_pending_request_for(self, path: str) -> None:
        # Landing later would make a repo the user has just closed active again.
        pending = self._pending_request()
        if pending is not None and pending.path == path:
            self._stop_waiting_for_request()

    def _repo_after_closing(self, path: str, skipping: str | None = None) -> str | None:
        """The open repo listed just before *path*, or after it when it is
        first, passing over *skipping*."""
        open_repos = self._repo_store.get_open_repos()
        index = open_repos.index(path) if path in open_repos else 0
        before = [p for p in open_repos[:index] if p != skipping]
        after = [p for p in open_repos[index:] if p not in (path, skipping)]
        return before[-1] if before else next(iter(after), None)

    def _close_current_repo(self) -> None:
        """Ctrl+W: close the active repo and switch to the previous open one."""
        if not self._repo_path:
            return
        self._on_repo_close(self._repo_path)

    def _switch_to_repo_index(self, index: int) -> None:
        """Ctrl+1..9: switch to the Nth open repo (1-based)."""
        open_repos = self._repo_store.get_open_repos()
        i = index - 1  # 0-based
        if i < 0 or i >= len(open_repos):
            return
        path = open_repos[i]
        if path == self._repo_path:
            return  # already active
        self._switch_repo(path)

    def _on_repo_remove_recent(self, path: str) -> None:
        self._repo_store.remove_recent(path)
        self.save_repo_list()
        self._repo_list.reload()

    # ── Worktree orchestration ────────────────────────────────────────────

    def _load_worktrees_for_active_repo(self) -> None:
        if self._queries is None or self._repo_path is None:
            return
        self._refresh_worktrees_dialog()
        try:
            wts = self._queries.list_worktrees.execute()
        except Exception as e:
            self._report_worktree_error(f"Failed to list worktrees: {e}")
            wts = []
        self._repo_list.set_active_worktrees(wts, owner_path=self._worktree_group_owner(wts))
        self._repo_list.reload()
        wt_branches = {wt.branch for wt in wts if wt.branch and not wt.is_main}
        wt_paths = {wt.branch: str(wt.path) for wt in wts if wt.branch and not wt.is_main}
        self._sidebar.set_worktree_branches(wt_branches)
        self._worktree_paths_by_branch = wt_paths

    def _worktree_group_owner(self, worktrees: list[Worktree]) -> str | None:
        """The open row the worktree group hangs under, spelled as the store has it.

        While a linked worktree is active, that is the open repo it belongs to:
        the worktree has no open row of its own, so without one it is nowhere
        in the list. A relaunch opens straight onto it with no owner recorded.

        The open repos' paths are compared as written, never resolved: this
        runs on the GUI thread, and resolving a path on a share that is down
        waits out its network timeout. An owner written another way, through
        a link say, is still known on a switch in from its own group.
        """
        open_repos = self._repo_store.get_open_repos()
        if self._repo_path in open_repos:
            return self._repo_path
        main = next((wt.path for wt in worktrees if wt.is_main), None)
        owner = next((p for p in open_repos if main and same_path_text(p, main)), None)
        if owner is None:
            owner = self._repo_list.owner_of(self._repo_path)
        return owner if owner in open_repos else None

    def _report_worktree_error(self, message: str) -> None:
        # The log starts collapsed, and a line added to it unopened is never
        # seen: a failed worktree operation would look like nothing happened.
        self._log_panel.expand()
        self._log_panel.log_error(message)

    def _on_worktree_action(self, action: str, path: str) -> None:
        if action == "add":
            self._open_add_worktree_dialog(preselect_branch=None, default_create=False)
        elif action == "manage":
            self._open_worktrees_dialog()
        elif action == "open":
            self._switch_repo(path)
        elif action == "lock":
            self._run_lock_worktree(path)
        elif action == "unlock":
            self._run_unlock_worktree(path)
        elif action == "remove":
            self._begin_remove_worktree(path)

    def _open_add_worktree_dialog(
        self,
        *,
        preselect_branch: str | None,
        default_create: bool,
    ) -> None:
        if self._queries is None or self._commands is None or self._repo_path is None:
            return
        from git_gui.presentation.dialogs.add_worktree_dialog import AddWorktreeDialog

        # Opening on a list that could not be read would offer a branch that is
        # already checked out as free, or offer nothing at all.
        try:
            branches = [b.name for b in self._queries.get_branches.execute() if not b.is_remote]
            worktrees = self._queries.list_worktrees.execute()
        except Exception as e:
            self._report_worktree_error(f"Cannot add a worktree: {e}")
            return
        dlg = AddWorktreeDialog(
            repo_path=_worktree_root(self._repo_path, worktrees),
            branches=branches,
            branches_in_use=_branches_in_use(worktrees),
            preselect_branch=preselect_branch,
            default_create_new=default_create,
            parent=self,
        )
        # The dialog is modal: a switch already on its way can land while the
        # user fills it in.
        asked_in = self._commands
        dlg.add_requested.connect(
            lambda payload: self._on_add_worktree_requested(payload, asked_in)
        )
        dlg.switch_to_existing_requested.connect(self._switch_repo)
        dlg.exec()

    def _open_worktrees_dialog(self) -> None:
        if self._queries is None or self._commands is None:
            return
        from git_gui.presentation.dialogs.worktrees_dialog import WorktreesDialog

        try:
            wts = self._queries.list_worktrees.execute()
        except Exception as e:
            self._report_worktree_error(f"Failed to list worktrees: {e}")
            return
        dlg = WorktreesDialog(worktrees=wts, parent=self)
        dlg.open_requested.connect(self._switch_repo)
        dlg.remove_requested.connect(self._begin_remove_worktree)
        dlg.lock_requested.connect(self._run_lock_worktree)
        dlg.unlock_requested.connect(self._run_unlock_worktree)
        dlg.add_requested.connect(
            lambda: self._open_add_worktree_dialog(preselect_branch=None, default_create=False)
        )
        self._worktrees_dialog = dlg
        try:
            dlg.exec()
        finally:
            self._worktrees_dialog = None

    def _refresh_worktrees_dialog(self) -> None:
        """Give the open Worktrees dialog the list as it is now.

        Its actions finish on background threads after it has emitted them,
        so without this its table keeps showing the state from before them.
        """
        dlg = self._worktrees_dialog
        if dlg is None:
            return
        try:
            dlg.set_worktrees(self._queries.list_worktrees.execute())
        except Exception as e:
            self._report_worktree_error(f"Failed to list worktrees: {e}")

    def _run_worktree_op(
        self,
        label: str,
        op: Callable[[CommandBus], object],
        on_done: Callable[[object], None],
        on_error: Callable[[Exception, CommandBus], bool] | None = None,
    ) -> None:
        """Run one worktree command off the GUI thread, on the repo open now.

        *on_done* gets the command's result back on the GUI thread. A failure
        *on_error* does not claim (by returning True) is reported as
        "<label> worktree failed: ...". *on_error* also gets the bus the
        command ran on: another repo may have opened since it started.
        """
        commands = self._commands
        if commands is None:
            return
        signals = _WorktreeOpSignals(self)

        def _worker():
            try:
                signals.done.emit(op(commands))
            except Exception as e:
                signals.failed.emit(e)

        def _failed(error: Exception) -> None:
            if on_error is None or not on_error(error, commands):
                self._report_worktree_error(f"{label} worktree failed: {error}")

        signals.done.connect(on_done)
        signals.failed.connect(_failed)
        signals.done.connect(signals.deleteLater)
        signals.failed.connect(signals.deleteLater)
        threading.Thread(target=_worker, daemon=True).start()

    def _on_add_worktree_requested(self, payload: dict, asked_in: CommandBus | None) -> None:
        if self._repo_switched_while_asking(asked_in, f"Add worktree {payload['branch']}"):
            return
        self._run_worktree_op(
            "Add",
            lambda commands: commands.add_worktree.execute(
                payload["location"],
                payload["branch"],
                create_branch=payload["create_new"],
                base_ref=payload["base_ref"],
            ),
            lambda wt: self._on_worktree_added(str(wt.path), payload["switch_after"]),
        )

    def _on_worktree_added(self, path: str, switch_after: bool) -> None:
        self._load_worktrees_for_active_repo()
        if switch_after:
            self._switch_repo(path)

    def _run_lock_worktree_with_reason(self, path: str, reason: str) -> None:
        self._run_worktree_op(
            "Lock",
            lambda commands: commands.lock_worktree.execute(path, reason=reason or None),
            lambda _: self._load_worktrees_for_active_repo(),
        )

    def _run_lock_worktree(self, path: str) -> None:
        from PySide6.QtWidgets import QInputDialog

        # The prompt is modal: a switch already on its way can land while it
        # is up, and that repo's git does not know this worktree.
        asked_in = self._commands
        text, ok = QInputDialog.getText(self, "Lock Worktree", "Reason (optional):")
        if not ok or self._repo_switched_while_asking(asked_in, f"Lock worktree {path}"):
            return
        self._run_lock_worktree_with_reason(path, text.strip())

    def _run_unlock_worktree(self, path: str) -> None:
        self._run_worktree_op(
            "Unlock",
            lambda commands: commands.unlock_worktree.execute(path),
            lambda _: self._load_worktrees_for_active_repo(),
        )

    def _begin_remove_worktree(self, path: str) -> None:
        from PySide6.QtWidgets import QMessageBox

        asked_in = self._commands
        answer = QMessageBox.question(self, "Remove worktree", f"Remove worktree at {path}?")
        if answer != QMessageBox.Yes:
            return
        self._remove_worktree_unless_switched(path, asked_in, force=False, override_lock=False)

    def _remove_worktree_unless_switched(
        self, path: str, asked_in: CommandBus | None, *, force: bool, override_lock: bool
    ) -> None:
        """Remove *path* as the user agreed, unless another repo opened while
        they were asked about it in *asked_in*: its git does not know *path*."""
        if not self._repo_switched_while_asking(asked_in, f"Remove worktree {path}"):
            self._run_remove_worktree(path, force=force, override_lock=override_lock)

    def _run_remove_worktree(self, path: str, *, force: bool, override_lock: bool = False) -> None:
        self._run_worktree_op(
            "Remove",
            lambda commands: commands.remove_worktree.execute(
                path, force=force, override_lock=override_lock
            ),
            lambda _: self._on_worktree_removed(path),
            lambda error, commands: self._offer_force_remove(
                path, error, commands, force=force, override_lock=override_lock
            ),
        )

    def _offer_force_remove(
        self,
        path: str,
        error: Exception,
        refused_in: CommandBus,
        *,
        force: bool,
        override_lock: bool,
    ) -> bool:
        """Offer to override what git refused the removal for; False for any
        other failure, and for one the user has already overridden.

        Each prompt grants only its own override and keeps the other: git
        checks the lock before the changes, so a locked worktree with changes
        is refused twice, and dropping the first override on the second retry
        would bring its prompt back.
        """
        # Dispatch by class name to keep this layer infra-free (the
        # architecture guard forbids importing the concrete error types here).
        name = type(error).__name__
        if name == "WorktreeDirtyError" and not force:
            self._on_remove_dirty(path, refused_in, override_lock=override_lock)
        elif name == "WorktreeLockedError" and not override_lock:
            self._on_remove_locked(path, str(error), refused_in, force=force)
        else:
            return False
        return True

    def _on_worktree_removed(self, path: str) -> None:
        """Leave the deleted directory rather than sitting in it.

        Removing the worktree you are currently in used to succeed and change
        nothing else: the active path, the window title and the repo store all
        went on naming a directory that no longer existed, and every read after
        that raised "head reference does not exist" until the user clicked
        another repo themselves.
        """
        self._repo_store.forget(path)
        self.save_repo_list()

        if path != self._repo_path:
            self._load_worktrees_for_active_repo()
            self._repo_list.reload()
            return

        home = self._home_after_removing(path)
        if home is None:
            self._log_panel.log(f"Removed worktree {path} — nothing left to open")
            self._enter_empty_state()
            return
        self._log_panel.log(f"Removed worktree {path} — switched to {home}")
        # The repo on screen is gone: one that fails to open leaves nothing
        # to show, not the deleted directory.
        self._request_repo(_RepoRequest(home, _SwitchReason.REPLACE))

    def _home_after_removing(self, removed: str) -> str | None:
        """Where to land once the worktree under us is gone.

        The repo that owned it comes first: it is what the worktree was a view
        of, it is certain to still exist, and it is the same place every time —
        picking an arbitrary sibling worktree would not be. A worktree opened
        on a row of its own is its own owner, and goes back to its main
        worktree. Siblings and the other open repos are the fallbacks.

        Only the removed worktree's own repository is looked for on disk: git
        has just reached it. Another open repo can be on a share that is down,
        and looking for it here, on the GUI thread, waits out the network
        timeout; the switch's worker finds out instead.
        """
        group = [
            self._repo_list.worktree_owner(),
            self._repo_list.main_worktree(),
            *self._worktree_paths_by_branch.values(),
        ]
        for candidate in group:
            if candidate and not same_path_text(candidate, removed) and Path(candidate).is_dir():
                return candidate
        others = self._repo_store.get_open_repos()
        return next((p for p in others if not same_path_text(p, removed)), None)

    def _on_remove_dirty(self, path: str, refused_in: CommandBus, *, override_lock: bool) -> None:
        from PySide6.QtWidgets import QMessageBox

        msg = QMessageBox(self)
        msg.setWindowTitle("Worktree is dirty")
        msg.setText(f"The worktree at {path} has uncommitted changes.\nForce remove anyway?")
        force = msg.addButton("Force remove", QMessageBox.DestructiveRole)
        msg.addButton("Cancel", QMessageBox.RejectRole)
        msg.exec()
        if msg.clickedButton() is force:
            self._remove_worktree_unless_switched(
                path, refused_in, force=True, override_lock=override_lock
            )

    def _on_remove_locked(
        self, path: str, reason: str, refused_in: CommandBus, *, force: bool
    ) -> None:
        from PySide6.QtWidgets import QMessageBox

        msg = QMessageBox(self)
        msg.setWindowTitle("Worktree is locked")
        msg.setText(f"The worktree at {path} is locked.\n{reason}\n\nForce remove anyway?")
        override = msg.addButton("Force remove", QMessageBox.DestructiveRole)
        msg.addButton("Cancel", QMessageBox.RejectRole)
        msg.exec()
        if msg.clickedButton() is override:
            # Lifting the lock alone: uncommitted changes still get their
            # own prompt.
            self._remove_worktree_unless_switched(path, refused_in, force=force, override_lock=True)
