"""Tests for creating a tag, optionally pushing it to origin."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QDialog

from git_gui.presentation.main_window.tag_flows import TagFlowsMixin

MODULE = "git_gui.presentation.main_window.tag_flows"


class _Host(TagFlowsMixin):
    """Bare composite standing in for MainWindow's attributes."""

    def __init__(self) -> None:
        self._queries = MagicMock()
        self._commands = MagicMock()
        self._log_panel = MagicMock()
        self._repo_path = "/repo"
        self._remote_running = False
        self.pushed: list[str] = []
        self.reloaded = 0

    def _reload(self) -> None:
        self.reloaded += 1

    def _on_push_tag(self, name: str) -> None:
        self.pushed.append(name)


def _remote(name: str) -> MagicMock:
    r = MagicMock()
    r.name = name
    return r


@pytest.fixture
def host():
    h = _Host()
    h._queries.list_remotes.execute.return_value = [_remote("origin")]
    return h


def _run(host, *, push: bool, accepted: bool = True):
    with patch(f"{MODULE}.CreateTagDialog") as factory:
        dialog = factory.return_value
        dialog.exec.return_value = QDialog.Accepted if accepted else QDialog.Rejected
        dialog.tag_name.return_value = "v1.0.0"
        dialog.tag_message.return_value = None
        dialog.push_requested.return_value = push
        host._on_create_tag("abc123")
    return factory


def test_create_without_push(host):
    _run(host, push=False)
    host._commands.create_tag.execute.assert_called_once_with("v1.0.0", "abc123", None)
    assert host.pushed == []


def test_create_with_push_pushes_the_new_tag(host):
    _run(host, push=True)
    host._commands.create_tag.execute.assert_called_once()
    assert host.pushed == ["v1.0.0"]


def test_failed_create_does_not_push(host):
    host._commands.create_tag.execute.side_effect = RuntimeError("tag exists")
    _run(host, push=True)
    assert host.pushed == []
    host._log_panel.log_error.assert_called_once()


def test_push_while_another_remote_op_runs_is_reported_not_dropped(host):
    host._remote_running = True
    _run(host, push=True)
    assert host.pushed == []
    assert "skipped" in host._log_panel.log_error.call_args.args[0]


def test_dialog_offers_push_only_when_origin_exists(host):
    factory = _run(host, push=False)
    assert factory.call_args.kwargs["can_push"] is True

    host._queries.list_remotes.execute.return_value = [_remote("upstream")]
    factory = _run(host, push=False)
    assert factory.call_args.kwargs["can_push"] is False


def test_cancel_creates_nothing(host):
    _run(host, push=True, accepted=False)
    host._commands.create_tag.execute.assert_not_called()
    assert host.pushed == []
