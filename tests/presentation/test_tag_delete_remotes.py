"""Deleting a tag locally and from every remote that has it."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

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

    def _run_remote_op(self, name: str, fn) -> None:
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
