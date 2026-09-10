"""Cancel-remote-op wiring in the main window (RemoteOpQueueMixin)."""

from unittest.mock import MagicMock, patch

from git_gui.presentation.main_window import MainWindow


def _make_window(qtbot):
    repo_store = MagicMock()
    repo_store.get_open_repos.return_value = []
    repo_store.get_recent_repos.return_value = []
    repo_store.get_active.return_value = None
    win = MainWindow(
        queries=None,
        commands=None,
        repo_store=repo_store,
        session_factory=lambda _p: (MagicMock(), MagicMock()),
    )
    qtbot.addWidget(win)
    win._commands = MagicMock()
    return win


def test_cancel_button_exists_and_starts_hidden(qtbot):
    win = _make_window(qtbot)
    assert win._cancel_remote_btn is not None
    assert not win._cancel_remote_btn.isVisibleTo(win)


def test_cancel_executes_command_when_running(qtbot):
    win = _make_window(qtbot)
    win._remote_running = True
    win._remote_op_name = "Push origin/main"

    win._cancel_remote_op()

    win._commands.cancel_remote_op.execute.assert_called_once_with()
    # Button is disabled to prevent a double-cancel while termination lands.
    assert not win._cancel_remote_btn.isEnabled()


def test_cancel_is_noop_when_idle(qtbot):
    win = _make_window(qtbot)
    win._remote_running = False

    win._cancel_remote_op()

    win._commands.cancel_remote_op.execute.assert_not_called()


def test_run_remote_op_shows_cancel_button(qtbot):
    win = _make_window(qtbot)
    win.show()
    with patch.object(win, "_reload"):
        win._run_remote_op("Fetch origin", lambda: None)
        # The button is revealed as soon as the op starts.
        assert win._cancel_remote_btn.isVisibleTo(win)
        assert win._remote_running is True
        qtbot.waitUntil(lambda: not win._remote_running, timeout=2000)
    # After completion the button is hidden again.
    assert not win._cancel_remote_btn.isVisibleTo(win)


def test_on_remote_cancelled_resets_state(qtbot):
    win = _make_window(qtbot)
    win.show()
    win._remote_running = True
    win._cancel_remote_btn.setVisible(True)
    with patch.object(win, "_reload"):
        win._on_remote_cancelled("Push origin/main")
    assert win._remote_running is False
    assert not win._cancel_remote_btn.isVisibleTo(win)


def test_second_op_ignored_while_running(qtbot):
    """Single-flight: a second remote op is dropped while one is in flight."""
    win = _make_window(qtbot)
    win._remote_running = True
    calls = []
    win._run_remote_op("Push", lambda: calls.append("ran"))
    assert calls == []  # worker never started
