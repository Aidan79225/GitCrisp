"""Which repo, branch and remote a remote operation acts on (RemoteOpQueueMixin)."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QMessageBox

from git_gui.domain.entities import Branch, LocalBranchInfo, TrackedBranch
from git_gui.presentation.main_window import MainWindow
from tests.presentation.window_helpers import blank_window

MODULE = "git_gui.presentation.main_window.remote_op_queue"
REJECTED = "! [rejected] feature -> feature (non-fast-forward)"


def _make_window(qtbot) -> MainWindow:
    win = blank_window(qtbot)
    win._commands = MagicMock()
    win._queries = _queries_on_branch("main", others=["feature"])
    return win


def _queries_on_branch(head: str | None, others: tuple[str, ...] | list[str] = ()) -> MagicMock:
    queries = MagicMock()
    branches = [Branch(name, False, False, "0" * 40) for name in others]
    if head is not None:
        branches.append(Branch(head, False, True, "1" * 40))
    queries.get_branches.execute.return_value = branches
    queries.list_local_branches_with_upstream.execute.return_value = []
    queries.list_remotes.execute.return_value = []
    return queries


def _wait_until_idle(qtbot, win: MainWindow) -> None:
    qtbot.waitUntil(lambda: not win._remote_running, timeout=2000)


def test_a_rejected_sidebar_push_offers_to_force_push_that_branch_not_head(qtbot):
    win = _make_window(qtbot)
    win._commands.push.execute.side_effect = RuntimeError(REJECTED)
    with (
        patch.object(win, "_reload"),
        patch(f"{MODULE}.QMessageBox.warning", return_value=QMessageBox.Yes) as warning,
    ):
        win._sidebar.branch_push_requested.emit("feature")
        qtbot.waitUntil(lambda: win._commands.force_push.execute.called, timeout=2000)
        _wait_until_idle(qtbot, win)

    win._commands.force_push.execute.assert_called_once_with("origin", "feature")
    assert "feature" in warning.call_args.args[2]


def test_a_rejected_push_force_pushes_in_the_repo_it_was_pushed_from(qtbot):
    win = _make_window(qtbot)
    pushed_from = win._commands
    switched = threading.Event()

    def _rejected_after_a_repo_switch(*_args):
        switched.wait(2)
        raise RuntimeError(REJECTED)

    pushed_from.push.execute.side_effect = _rejected_after_a_repo_switch
    with (
        patch.object(win, "_reload"),
        patch(f"{MODULE}.QMessageBox.warning", return_value=QMessageBox.Yes),
    ):
        win._on_push()
        win._commands = MagicMock()
        win._queries = _queries_on_branch("other")
        switched.set()
        qtbot.waitUntil(lambda: pushed_from.force_push.execute.called, timeout=2000)
        _wait_until_idle(qtbot, win)

    pushed_from.force_push.execute.assert_called_once_with("origin", "main")
    win._commands.force_push.execute.assert_not_called()


def test_a_rejected_tag_push_does_not_offer_to_force_push_a_branch(qtbot):
    win = _make_window(qtbot)
    with (
        patch.object(win, "_reload"),
        patch(f"{MODULE}.QMessageBox.warning") as warning,
    ):
        win._on_remote_error("Push tag v1", REJECTED)

    warning.assert_not_called()


def _cancel_after(win: MainWindow, replace_active_commands) -> MagicMock:
    """Start an op, swap the active bus as a repo switch would, then Cancel."""
    started_in = win._commands
    release = threading.Event()
    win._run_remote_op("Fetch --all --prune", lambda: release.wait(2))
    replace_active_commands()
    win._cancel_remote_op()
    release.set()
    return started_in


def test_cancel_after_a_repo_switch_stops_the_op_in_the_repo_it_started_in(qtbot):
    win = _make_window(qtbot)
    with patch.object(win, "_reload"):
        started_in = _cancel_after(win, lambda: setattr(win, "_commands", MagicMock()))
        _wait_until_idle(qtbot, win)

    started_in.cancel_remote_op.execute.assert_called_once_with()
    win._commands.cancel_remote_op.execute.assert_not_called()


def test_cancel_after_closing_the_last_repo_still_stops_the_op(qtbot):
    win = _make_window(qtbot)
    with patch.object(win, "_reload"):
        started_in = _cancel_after(win, lambda: setattr(win, "_commands", None))
        _wait_until_idle(qtbot, win)

    started_in.cancel_remote_op.execute.assert_called_once_with()


def test_an_op_requested_while_another_runs_is_reported_as_skipped(qtbot):
    win = _make_window(qtbot)
    win._log_panel = MagicMock()
    release = threading.Event()
    skipped = []
    with patch.object(win, "_reload"):
        win._run_remote_op("Delete tag v1 from origin", lambda: release.wait(2))
        win._run_remote_op("Delete tag v1 from upstream", lambda: skipped.append("ran"))
        release.set()
        _wait_until_idle(qtbot, win)

    assert skipped == []
    errors = [call.args[0] for call in win._log_panel.log_error.call_args_list]
    assert any(
        "Delete tag v1 from upstream — skipped" in e and "Delete tag v1 from origin" in e
        for e in errors
    ), errors


def _switch_to_repo_b(win: MainWindow) -> None:
    win._commands = MagicMock()
    win._queries = MagicMock()
    win._queries.get_remote_tags.execute.return_value = ["b-tag"]
    win._repo_path = "/repo/b"


def test_the_tag_cache_after_a_fetch_is_saved_for_the_repo_that_was_fetched(qtbot):
    win = _make_window(qtbot)
    win._remote_tag_cache = MagicMock()
    win._remote_tag_cache.load.return_value = {}
    win._repo_path = "/repo/a"
    win._queries.get_remote_tags.execute.return_value = ["a-tag"]
    fetched_in = win._commands
    fetched_in.fetch.execute.side_effect = lambda _remote: _switch_to_repo_b(win)
    with patch.object(win, "_reload"):
        win._on_fetch_single("origin")
        _wait_until_idle(qtbot, win)

    win._remote_tag_cache.save.assert_called_once_with("/repo/a", {"origin": ["a-tag"]})
    fetched_in.fetch.execute.assert_called_once_with("origin")


@pytest.mark.parametrize("slot", ["_on_push", "_on_pull"])
def test_push_or_pull_with_no_branch_checked_out_says_why_nothing_ran(qtbot, slot):
    win = _make_window(qtbot)
    win._queries = _queries_on_branch(None, others=["main"])  # detached HEAD
    win._log_panel = MagicMock()

    getattr(win, slot)()

    assert win._remote_running is False
    win._log_panel.expand.assert_called_once_with()
    assert "check out a branch" in win._log_panel.log_error.call_args.args[0].lower()


def _window_on(qtbot, info: LocalBranchInfo, others: tuple[str, ...] = ()) -> MainWindow:
    """A window with *info*'s branch checked out beside the local *others*."""
    win = _make_window(qtbot)
    win._queries = _queries_on_branch(info.name, others=others)
    win._queries.list_local_branches_with_upstream.execute.return_value = [info]
    return win


def _pull(qtbot, win: MainWindow) -> str:
    """Pull on *win*; returns the log."""
    with patch.object(win, "_reload"):
        win._on_pull()
        _wait_until_idle(qtbot, win)
    return win._log_panel._body.toPlainText()


def _info(name: str, upstream: str | None, tracks: TrackedBranch | None) -> LocalBranchInfo:
    return LocalBranchInfo(name, upstream, "0123456789", "Fix it", tracks)


@pytest.mark.parametrize(
    ("info", "label"),
    [
        # A fork: origin is the user's own copy, main tracks the canonical repo.
        (
            _info("main", "upstream/main", TrackedBranch("upstream", "refs/heads/main")),
            "upstream/main",
        ),
        (
            _info("rel", "origin/release/1.x", TrackedBranch("origin", "refs/heads/release/1.x")),
            "origin/release/1.x",
        ),
        (
            _info("topic", "gh/fork/topic", TrackedBranch("gh/fork", "refs/heads/topic")),
            "gh/fork/topic",
        ),
    ],
    ids=["upstream-on-another-remote", "upstream-under-another-name", "remote-with-a-slash"],
)
def test_pull_takes_the_ref_the_branch_tracks_from_that_remote(qtbot, info, label):
    win = _window_on(qtbot, info)

    log = _pull(qtbot, win)

    win._commands.pull.execute.assert_called_once_with(info.tracks.remote, info.tracks.ref)
    assert f"Pull {label} — done" in log


def test_pull_with_no_upstream_takes_the_same_named_branch_from_origin(qtbot):
    win = _window_on(qtbot, _info("fix", None, None))

    _pull(qtbot, win)

    win._commands.pull.execute.assert_called_once_with("origin", "refs/heads/fix")


def test_pull_still_runs_when_the_repos_remotes_cannot_be_listed(qtbot):
    # One remote with an invalid name in .git/config makes pygit2 fail the
    # whole listing, while `git pull` itself works fine.
    win = _window_on(
        qtbot, _info("main", "upstream/main", TrackedBranch("upstream", "refs/heads/main"))
    )
    win._queries.list_remotes.execute.side_effect = RuntimeError("'bad name' is not valid")

    _pull(qtbot, win)

    win._commands.pull.execute.assert_called_once_with("upstream", "refs/heads/main")


@pytest.mark.parametrize("upstream", ["feature/login", "main"])
def test_pull_takes_a_local_upstream_from_this_repo_not_from_a_remote(qtbot, upstream):
    # `git checkout -b topic --track feature/login` stacks topic on a local
    # branch (branch.topic.remote = '.'): no remote is named "feature".
    tracks = TrackedBranch(".", f"refs/heads/{upstream}")
    win = _window_on(qtbot, _info("topic", upstream, tracks), others=(upstream,))

    log = _pull(qtbot, win)

    win._commands.pull.execute.assert_called_once_with(".", f"refs/heads/{upstream}")
    assert f"Pull {upstream} — done" in log


@pytest.mark.parametrize(
    ("local", "tracks"),
    [
        ("main", TrackedBranch("origin", "refs/heads/main")),
        ("topic", TrackedBranch(".", "refs/heads/origin/main")),
    ],
    ids=["tracks-origins-main", "tracks-the-local-branch"],
)
def test_pull_takes_what_the_branch_tracks_when_a_local_branch_shares_the_upstreams_name(
    qtbot, local, tracks
):
    # Beside a local branch named "origin/main", the upstream shorthand
    # "origin/main" names either that branch or origin's main.
    win = _window_on(qtbot, _info(local, "origin/main", tracks), others=("origin/main",))

    log = _pull(qtbot, win)

    win._commands.pull.execute.assert_called_once_with(tracks.remote, tracks.ref)
    assert "Pull origin/main — done" in log


def test_the_log_says_why_the_remotes_could_not_be_listed(qtbot):
    win = _make_window(qtbot)
    win._queries.list_remotes.execute.side_effect = RuntimeError(
        "'bad name' is not a valid remote name"
    )

    assert win._remote_names() == []
    assert "'bad name' is not a valid remote name" in win._log_panel._body.toPlainText()


@pytest.mark.parametrize(
    ("start", "command", "args", "remote"),
    [
        (lambda win: win._on_fetch_all_prune(), "fetch_all_prune", (), "origin"),
        (lambda win: win._on_fetch_single("upstream"), "fetch", ("upstream",), "upstream"),
        (lambda win: win._on_push_tag("v1"), "push_tag", ("origin", "v1"), "origin"),
    ],
    ids=["fetch-all", "fetch-one", "push-tag"],
)
def test_an_op_that_changes_remote_tags_refreshes_that_remotes_cached_tags(
    qtbot, start, command, args, remote
):
    win = _make_window(qtbot)
    win._remote_tag_cache = MagicMock()
    win._remote_tag_cache.load.return_value = {}
    win._repo_path = "/repo/a"
    win._queries.get_remote_tags.execute.return_value = ["v1"]
    with patch.object(win, "_reload"):
        start(win)
        _wait_until_idle(qtbot, win)

    getattr(win._commands, command).execute.assert_called_once_with(*args)
    win._queries.get_remote_tags.execute.assert_called_once_with(remote)
    win._remote_tag_cache.save.assert_called_once_with("/repo/a", {remote: ["v1"]})
