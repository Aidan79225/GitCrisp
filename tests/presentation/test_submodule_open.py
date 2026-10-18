"""Opening a submodule from a diff header or the Submodules dialog (RightPanelMixin)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from git_gui.presentation.main_window import MainWindow
from git_gui.presentation.main_window.repo_lifecycle import _RepoRequest, _SwitchReason
from tests.presentation.window_helpers import blank_window


def _make_window(qtbot, repo_path) -> MainWindow:
    win = blank_window(qtbot)
    win._repo_path = str(repo_path)
    win._log_panel = MagicMock()
    return win


def test_an_uninitialized_submodule_is_reported_instead_of_opening_its_parent(qtbot, tmp_path):
    (tmp_path / "lib").mkdir()  # a clone made without --recursive
    win = _make_window(qtbot, tmp_path)

    with patch.object(win, "_request_repo") as request:
        win._on_submodule_path_clicked("lib")

    request.assert_not_called()
    win._log_panel.expand.assert_called_once_with()
    assert "git submodule update --init" in win._log_panel.log_error.call_args.args[0]


def test_an_initialized_submodule_opens_as_its_own_repo(qtbot, tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / ".git").write_text("gitdir: ../.git/modules/lib\n", encoding="utf-8")
    win = _make_window(qtbot, tmp_path)

    with patch.object(win, "_request_repo") as request:
        win._on_submodule_path_clicked("lib")

    request.assert_called_once_with(_RepoRequest(str(lib), _SwitchReason.OPEN, after=str(tmp_path)))
    win._log_panel.log_error.assert_not_called()
