"""Open Repository on a folder whose .git file git cannot follow.

An interrupted submodule checkout or a sync-tool conflict can leave .git as an
empty file, and discover_repository raises on it rather than answering. The
error escaped the button's slot: logged as an uncaught exception, with neither
the "Not a Git Repository" warning nor git's error shown, so the click looked
like it did nothing.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFileDialog, QMessageBox

from git_gui.presentation.widgets.repo_list import RepoListWidget
from tests.presentation.widgets.test_repo_list_worktrees import _FakeStore


def _choosing(monkeypatch, folder: str) -> None:
    monkeypatch.setattr(QFileDialog, "exec", lambda _self: QFileDialog.Accepted)
    monkeypatch.setattr(QFileDialog, "selectedFiles", lambda _self: [folder])


def _repo_list(qtbot) -> RepoListWidget:
    w = RepoListWidget(_FakeStore())
    qtbot.addWidget(w)
    return w


def test_a_folder_with_a_broken_git_file_is_opened_so_the_switch_says_why(
    qtbot, tmp_path, monkeypatch
):
    folder = tmp_path / "half-checked-out"
    folder.mkdir()
    (folder / ".git").write_bytes(b"")
    _choosing(monkeypatch, str(folder))
    w = _repo_list(qtbot)

    with qtbot.waitSignal(w.repo_open_requested, timeout=1000) as opened:
        w._on_add_clicked()

    assert opened.args == [str(folder)]


def test_a_folder_outside_any_repo_is_still_refused(qtbot, tmp_path, monkeypatch):
    folder = tmp_path / "plain"
    folder.mkdir()
    _choosing(monkeypatch, str(folder))
    warned: list[str] = []

    def _warn(_parent, title, _text):
        warned.append(title)
        monkeypatch.setattr(QFileDialog, "exec", lambda _self: QFileDialog.Rejected)

    monkeypatch.setattr(QMessageBox, "warning", _warn)
    w = _repo_list(qtbot)
    opened: list[str] = []
    w.repo_open_requested.connect(opened.append)

    w._on_add_clicked()

    assert warned == ["Not a Git Repository"]
    assert opened == []
