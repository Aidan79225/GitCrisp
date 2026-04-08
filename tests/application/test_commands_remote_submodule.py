from unittest.mock import MagicMock
from git_gui.application.commands import (
    AddRemote, RemoveRemote, RenameRemote, SetRemoteUrl,
    AddSubmodule, RemoveSubmodule, SetSubmoduleUrl,
)


def test_add_remote():
    w = MagicMock()
    AddRemote(w).execute("origin", "git@x:a.git")
    w.add_remote.assert_called_once_with("origin", "git@x:a.git")


def test_remove_remote():
    w = MagicMock()
    RemoveRemote(w).execute("origin")
    w.remove_remote.assert_called_once_with("origin")


def test_rename_remote():
    w = MagicMock()
    RenameRemote(w).execute("origin", "upstream")
    w.rename_remote.assert_called_once_with("origin", "upstream")


def test_set_remote_url():
    w = MagicMock()
    SetRemoteUrl(w).execute("origin", "git@x:b.git")
    w.set_remote_url.assert_called_once_with("origin", "git@x:b.git")


def test_add_submodule():
    w = MagicMock()
    AddSubmodule(w).execute("libs/foo", "git@x:foo.git")
    w.add_submodule.assert_called_once_with("libs/foo", "git@x:foo.git")


def test_remove_submodule():
    w = MagicMock()
    RemoveSubmodule(w).execute("libs/foo")
    w.remove_submodule.assert_called_once_with("libs/foo")


def test_set_submodule_url():
    w = MagicMock()
    SetSubmoduleUrl(w).execute("libs/foo", "git@x:bar.git")
    w.set_submodule_url.assert_called_once_with("libs/foo", "git@x:bar.git")
