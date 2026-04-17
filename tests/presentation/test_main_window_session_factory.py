"""Regression tests for the session_factory injection — verifies
MainWindow never imports infrastructure directly and delegates repo
opening to an injected callable."""
from __future__ import annotations

import pathlib
from unittest.mock import MagicMock

from git_gui.presentation.main_window import MainWindow


def _dummy_store() -> MagicMock:
    store = MagicMock()
    store.get_open_repos.return_value = []
    store.get_recent_repos.return_value = []
    store.get_active.return_value = None
    return store


def _make_window(qtbot, factory) -> MainWindow:
    win = MainWindow(
        queries=None,
        commands=None,
        repo_store=_dummy_store(),
        session_factory=factory,
    )
    qtbot.addWidget(win)
    return win


def test_switch_repo_invokes_session_factory(qtbot):
    """_switch_repo must call the injected factory on a worker thread and
    emit `ready` with the factory's return values."""
    fake_queries = MagicMock(name="queries")
    fake_commands = MagicMock(name="commands")
    factory = MagicMock(return_value=(fake_queries, fake_commands))

    win = _make_window(qtbot, factory)

    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=2000) as blocker:
        win._switch_repo("/some/path")

    assert factory.call_count == 1
    assert factory.call_args.args == ("/some/path",)
    path, queries, commands = blocker.args
    assert path == "/some/path"
    assert queries is fake_queries
    assert commands is fake_commands


def test_switch_repo_factory_failure_emits_failed_signal(qtbot):
    """If the factory raises, MainWindow emits `failed` with the error
    string — no exception escapes the worker."""
    factory = MagicMock(side_effect=RuntimeError("boom"))

    win = _make_window(qtbot, factory)

    with qtbot.waitSignal(win._repo_ready_signals.failed, timeout=2000) as blocker:
        win._switch_repo("/broken/path")

    path, error = blocker.args
    assert path == "/broken/path"
    assert "boom" in error


def test_main_window_source_does_not_import_infrastructure():
    """Regression guard: main_window.py must not reference
    git_gui.infrastructure in any import form."""
    import git_gui.presentation.main_window as mw_mod
    source = pathlib.Path(mw_mod.__file__).read_text(encoding="utf-8")
    assert "git_gui.infrastructure" not in source, (
        "main_window.py must not import from git_gui.infrastructure — "
        "use the injected session_factory instead."
    )
