"""Dropping a stash asks first: a dropped stash is only findable with git fsck."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QMessageBox

from git_gui.presentation.main_window.stash_flows import StashFlowsMixin


class _Host(StashFlowsMixin):
    """Bare composite standing in for MainWindow's attributes."""

    def __init__(self) -> None:
        self._commands = MagicMock()
        self._log_panel = MagicMock()

    def _reload(self) -> None:
        pass


def _drop(answer) -> tuple[_Host, MagicMock]:
    host = _Host()
    with patch.object(QMessageBox, "question", return_value=answer) as question:
        host._on_stash_drop(2)
    return host, question


def test_declining_keeps_the_stash():
    host, question = _drop(QMessageBox.No)
    assert "stash@{2}" in question.call_args.args[2]
    host._commands.drop_stash.execute.assert_not_called()


def test_confirming_drops_it():
    host, _question = _drop(QMessageBox.Yes)
    host._commands.drop_stash.execute.assert_called_once_with(2)
