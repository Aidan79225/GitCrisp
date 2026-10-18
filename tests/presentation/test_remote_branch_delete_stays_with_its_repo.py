"""A remote-branch delete runs against the repo it was confirmed in.

The op runs on a worker thread after the confirmation, and it read the
window's command bus only when it ran. A repo switch in between sent the
delete to the newly opened repo's remote instead.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QMessageBox

from git_gui.presentation.main_window import MainWindow
from tests.presentation.window_helpers import wired_window


def _make_window(qtbot) -> MainWindow:
    win = wired_window(qtbot)
    return win


def test_a_repo_switch_before_the_delete_runs_does_not_redirect_it(qtbot):
    win = _make_window(qtbot)
    queued: dict = {}
    with (
        patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
        patch.object(
            win, "_run_remote_op", side_effect=lambda _n, fn, **kw: queued.update(fn=fn, **kw)
        ),
    ):
        win._on_delete_remote_branch("origin", "topic")
    confirmed_in = win._commands
    win._commands = MagicMock()  # another repo opened meanwhile

    queued["fn"]()

    confirmed_in.delete_remote_branch.execute.assert_called_once_with("origin", "topic")
    win._commands.delete_remote_branch.execute.assert_not_called()
    assert queued["commands"] is confirmed_in
