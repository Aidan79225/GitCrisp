"""Deleting a tag locally and from every remote that has it."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from git_gui.domain.ports import RemoteOperationCancelled
from git_gui.presentation.main_window.remote_op_queue import RemoteOpQueueMixin
from git_gui.presentation.main_window.tag_flows import TagFlowsMixin


class _Host(TagFlowsMixin, RemoteOpQueueMixin):
    """Bare composite standing in for MainWindow's attributes."""

    def __init__(self) -> None:
        self._commands = MagicMock()
        self._log_panel = MagicMock()
        self._remote_tag_cache = MagicMock()
        self._remote_tag_cache.load.return_value = {"origin": ["v1"], "upstream": ["v1", "v2"]}
        self._repo_path = "/repo"
        self._remote_running = False
        self._remote_op_name: str | None = None
        self.ops: list[tuple[str, object]] = []

    def _reload(self) -> None:
        pass

    def _run_remote_op(self, name: str, fn, *, commands=None) -> None:
        # Single-flight, as RemoteOpQueueMixin is: the flag is set as the op
        # starts and cleared only once it finishes, and a request that
        # arrives meanwhile is dropped.
        if self._remote_running:
            return
        self._remote_running = True
        self.ops.append((name, fn))

    def finish_ops(self) -> None:
        for _name, fn in self.ops:
            fn()


@pytest.fixture
def host():
    return _Host()


def test_the_tag_is_deleted_from_every_remote(host):
    host._delete_tag_local_and_remote("v1", ["origin", "upstream"])
    host.finish_ops()
    assert host._commands.delete_remote_tag.execute.call_args_list == [
        call("origin", "v1"),
        call("upstream", "v1"),
    ]


def test_every_remote_drops_the_tag_from_its_cache(host):
    host._delete_tag_local_and_remote("v1", ["origin", "upstream"])
    host.finish_ops()
    saved = host._remote_tag_cache.save.call_args.args[1]
    assert saved == {"origin": [], "upstream": ["v2"]}


def test_while_another_remote_op_runs_nothing_is_deleted_and_the_user_is_told(host):
    host._remote_running = True
    host._delete_tag_local_and_remote("v1", ["origin", "upstream"])
    host._commands.delete_tag.execute.assert_not_called()
    assert host.ops == []
    assert "skipped" in host._log_panel.log_error.call_args.args[0]


def test_a_skipped_delete_names_the_op_that_holds_the_slot(host):
    host._remote_running = True
    host._remote_op_name = "Fetch origin"
    host._delete_tag_local_and_remote("v1", ["origin", "upstream"])
    assert "Fetch origin" in host._log_panel.log_error.call_args.args[0]


def _switch_repo(host) -> MagicMock:
    """Make another repo active, as switching tabs does; returns the bus it replaced."""
    started_in = host._commands
    host._commands, host._repo_path = MagicMock(), "/other"
    return started_in


def test_a_repo_switch_while_the_delete_runs_leaves_the_new_repo_alone(host):
    host._delete_tag_local_and_remote("v1", ["origin", "upstream"])
    started_in = _switch_repo(host)
    host.finish_ops()
    assert started_in.delete_remote_tag.execute.call_count == 2
    host._commands.delete_remote_tag.execute.assert_not_called()


def test_a_repo_switch_while_the_delete_runs_prunes_the_cache_of_the_repo_it_ran_in(host):
    host._delete_tag_local_and_remote("v1", ["origin", "upstream"])
    _switch_repo(host)
    host.finish_ops()
    assert {c.args[0] for c in host._remote_tag_cache.save.call_args_list} == {"/repo"}


def _refuse(*refusing: str):
    def _delete(remote: str, _name: str) -> None:
        if remote in refusing:
            raise RuntimeError(f"{remote} is unreachable")

    return _delete


def test_a_remote_that_fails_does_not_stop_the_delete_on_the_others(host):
    host._commands.delete_remote_tag.execute.side_effect = _refuse("origin")
    host._delete_tag_local_and_remote("v1", ["origin", "upstream"])
    with pytest.raises(RuntimeError):
        host.finish_ops()
    assert call("upstream", "v1") in host._commands.delete_remote_tag.execute.call_args_list


def test_the_error_names_the_remotes_that_still_have_the_tag(host):
    host._commands.delete_remote_tag.execute.side_effect = _refuse("origin")
    host._delete_tag_local_and_remote("v1", ["origin", "upstream"])
    with pytest.raises(RuntimeError, match=r"still on origin \(origin is unreachable\)$"):
        host.finish_ops()


def test_only_the_remotes_it_left_keep_the_tag_in_the_cache(host):
    host._commands.delete_remote_tag.execute.side_effect = _refuse("origin")
    host._delete_tag_local_and_remote("v1", ["origin", "upstream"])
    with pytest.raises(RuntimeError):
        host.finish_ops()
    saved = host._remote_tag_cache.save.call_args.args[1]
    assert saved == {"origin": ["v1"], "upstream": ["v2"]}


def test_a_cancel_stops_the_delete_before_the_remaining_remotes(host):
    def _cancel_on_origin(remote: str, _name: str) -> None:
        if remote == "origin":
            raise RemoteOperationCancelled("Operation cancelled")

    host._commands.delete_remote_tag.execute.side_effect = _cancel_on_origin
    host._delete_tag_local_and_remote("v1", ["origin", "upstream"])
    with pytest.raises(RemoteOperationCancelled):
        host.finish_ops()
    assert call("upstream", "v1") not in host._commands.delete_remote_tag.execute.call_args_list
