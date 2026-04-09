from unittest.mock import MagicMock
from git_gui.domain.entities import Remote, Submodule
from git_gui.application.queries import ListRemotes, ListSubmodules


def test_list_remotes_calls_reader():
    reader = MagicMock()
    reader.list_remotes.return_value = [Remote("origin", "u", "u")]
    q = ListRemotes(reader)
    assert q.execute() == [Remote("origin", "u", "u")]
    reader.list_remotes.assert_called_once()


def test_list_submodules_calls_reader():
    reader = MagicMock()
    reader.list_submodules.return_value = [Submodule("libs/x", "u", "abc")]
    q = ListSubmodules(reader)
    assert q.execute() == [Submodule("libs/x", "u", "abc")]
    reader.list_submodules.assert_called_once()
