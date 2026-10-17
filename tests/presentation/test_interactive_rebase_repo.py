"""An interactive rebase runs in, and is cancelled in, the repo it was planned in."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from git_gui.presentation.main_window.merge_rebase_flows import MergeRebaseFlowsMixin
from git_gui.presentation.main_window.remote_op_queue import RemoteOpQueueMixin

MODULE = "git_gui.presentation.main_window.merge_rebase_flows"
OID = "a" * 40
PLAN = ["pick"]


class _Host(MergeRebaseFlowsMixin, RemoteOpQueueMixin):
    """Bare composite standing in for MainWindow's attributes."""

    def __init__(self) -> None:
        self._queries = MagicMock()
        self._queries.get_head_oid.execute.return_value = "h" * 40
        self._queries.get_commit_range.execute.return_value = [MagicMock()]
        self._commands = MagicMock()
        self._log_panel = MagicMock()
        self._remote_running = False
        self._remote_op_name: str | None = None
        self.ops: list[tuple[object, object]] = []

    def _run_remote_op(self, name: str, fn, *, commands=None) -> None:
        self.ops.append((fn, commands))


@pytest.fixture
def host():
    return _Host()


def _plan_rebase(host: _Host) -> MagicMock:
    """Accept an interactive rebase plan; returns the bus active at that moment."""
    with patch(f"{MODULE}.InteractiveRebaseDialog") as dialog_cls:
        dialog_cls.return_value.exec.return_value = dialog_cls.Accepted
        dialog_cls.return_value.result_entries.return_value = PLAN
        host._on_interactive_rebase_commit(OID)
    return host._commands


def test_a_repo_switch_before_the_worker_starts_leaves_the_new_repo_alone(host):
    planned_in = _plan_rebase(host)
    host._commands = MagicMock()
    (rebase, _commands), *_ = host.ops
    rebase()
    planned_in.interactive_rebase.execute.assert_called_once_with(OID, PLAN)
    host._commands.interactive_rebase.execute.assert_not_called()


def test_cancel_goes_to_the_repo_the_rebase_was_planned_in(host):
    planned_in = _plan_rebase(host)
    (_rebase, commands), *_ = host.ops
    assert commands is planned_in
