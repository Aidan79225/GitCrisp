"""An Undo link in the log undoes something in one repository, and only there.

The links outlived a repo switch, and clicking one ran its reset against
whichever repository was open by then. A linked worktree shares the object
database, so the old commit resolved there and the dialog offered to
hard-reset an unrelated branch to it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog

from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.presentation.main_window import MainWindow

MODULE = "git_gui.presentation.main_window.reflog_flow"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def main_and_linked(tmp_path) -> tuple[Path, Path]:
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "master", ".")
    _git(main, "config", "user.name", "T")
    _git(main, "config", "user.email", "t@e.com")
    (main / "a.txt").write_text("x\n")
    _git(main, "add", "a.txt")
    _git(main, "commit", "-qm", "init")
    linked = tmp_path / "linked"
    _git(main, "worktree", "add", "-q", "-b", "feat", str(linked))
    return main, linked


@pytest.fixture
def window(qtbot, tmp_path, main_and_linked):
    from main import _open_session

    main, _linked = main_and_linked
    queries, commands = _open_session(str(main))
    w = MainWindow(
        queries,
        commands,
        JsonRepoStore(tmp_path / "repos.json"),
        JsonRemoteTagCache(),
        str(main),
        session_factory=_open_session,
    )
    qtbot.addWidget(w)
    return w


@pytest.fixture
def dialogs(monkeypatch) -> list[dict]:
    """Every reset dialog the click opens; each one is declined."""
    opened: list[dict] = []

    class _Recording:
        Accepted = QDialog.Accepted

        def __init__(self, **kwargs) -> None:
            opened.append(kwargs)

        def exec(self):
            return QDialog.Rejected

    monkeypatch.setattr(f"{MODULE}.ResetDialog", _Recording)
    return opened


def _log_an_undo(window) -> str:
    head = window.head_before_operation()
    window._log_undoable("Rebase onto main", head)
    return head


def _switch(qtbot, window, path: Path) -> None:
    with qtbot.waitSignal(window._repo_ready_signals.ready, timeout=5000):
        window._switch_repo(str(path))


def test_an_undo_from_another_repo_offers_no_reset(qtbot, window, dialogs, main_and_linked):
    _main, linked = main_and_linked
    head = _log_an_undo(window)
    _switch(qtbot, window, linked)

    window._log_panel.action_triggered.emit(head)

    assert dialogs == []
    assert "no longer applies" in window._log_panel._body.toPlainText()


def test_an_undo_after_closing_every_repo_offers_no_reset(window, dialogs):
    head = _log_an_undo(window)
    window._enter_empty_state()

    window._log_panel.action_triggered.emit(head)

    assert dialogs == []
    assert "ERROR" not in window._log_panel._body.toPlainText()


def test_reopening_the_same_repo_keeps_its_undo(qtbot, window, dialogs, main_and_linked):
    """Clicking the repo you are already in rebuilds its session; the undo it
    logged still belongs to it."""
    main, _linked = main_and_linked
    head = _log_an_undo(window)
    _switch(qtbot, window, main)

    window._log_panel.action_triggered.emit(head)

    assert [d["branch_name"] for d in dialogs] == ["master"]
