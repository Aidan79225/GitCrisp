"""git operations use the ssh command the user configured, not ours.

git ranks GIT_SSH_COMMAND above core.sshCommand, so setting it (for
accept-new host keys) silently replaced the user's own ssh: a Windows OpenSSH
agent, 1Password's, or a per-repo key. The fake ssh here prints a marker and
fails, so the error git reports says which ssh ran.
"""

from __future__ import annotations

import pygit2
import pytest

from git_gui.infrastructure.git_clone import clone_repo
from git_gui.infrastructure.pygit2 import Pygit2Repository
from git_gui.infrastructure.submodule_cli import SubmoduleCommandError

_MARKER = "custom ssh ran"
_SSH_COMMAND = f"echo {_MARKER} >&2; false"
_UNREACHABLE = "ssh://example.invalid/repo.git"


@pytest.fixture
def no_ssh_in_env(monkeypatch):
    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    monkeypatch.delenv("GIT_SSH", raising=False)


@pytest.fixture
def global_ssh_command(tmp_path, monkeypatch, no_ssh_in_env):
    """core.sshCommand in the user's global config, where both git and libgit2 read it."""
    home = tmp_path / "home"
    home.mkdir()
    gitconfig = home / ".gitconfig"
    gitconfig.touch()
    pygit2.Config(str(gitconfig))["core.sshCommand"] = _SSH_COMMAND
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    level = pygit2.enums.ConfigLevel.GLOBAL
    saved = pygit2.settings.search_path[level]
    pygit2.settings.search_path[level] = str(home)
    yield
    pygit2.settings.search_path[level] = saved


def test_a_fetch_uses_the_ssh_command_the_repository_configures(repo_path, no_ssh_in_env):
    pygit2.Repository(str(repo_path)).config["core.sshCommand"] = _SSH_COMMAND

    with pytest.raises(RuntimeError, match=_MARKER):
        Pygit2Repository(str(repo_path)).fetch(_UNREACHABLE)


def test_adding_a_submodule_uses_the_ssh_command_the_user_configures(global_ssh_command, repo_path):
    repo = Pygit2Repository(str(repo_path))

    with pytest.raises(SubmoduleCommandError, match=_MARKER):
        repo.add_submodule("lib", _UNREACHABLE)


def test_a_clone_uses_the_ssh_command_the_user_configures(global_ssh_command, tmp_path):
    with pytest.raises(RuntimeError, match=_MARKER):
        clone_repo(_UNREACHABLE, str(tmp_path / "dest"))


@pytest.fixture
def ssh_command_for_the_remote(tmp_path, monkeypatch, no_ssh_in_env):
    """core.sshCommand included only for repos with an example.invalid remote,
    the usual setup for a second account: git honours it, libgit2 does not."""
    home = tmp_path / "home"
    home.mkdir()
    work_config = home / ".gitconfig-work"
    work_config.write_text(f'[core]\n\tsshCommand = "{_SSH_COMMAND}"\n', encoding="utf-8")
    gitconfig = home / ".gitconfig"
    gitconfig.write_text(
        '[includeIf "hasconfig:remote.*.url:ssh://example.invalid/**"]\n'
        f"\tpath = {work_config.as_posix()}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    level = pygit2.enums.ConfigLevel.GLOBAL
    saved = pygit2.settings.search_path[level]
    pygit2.settings.search_path[level] = str(home)
    yield
    pygit2.settings.search_path[level] = saved


def test_a_fetch_uses_the_ssh_command_a_remote_url_include_configures(
    ssh_command_for_the_remote, repo_path
):
    pygit2.Repository(str(repo_path)).remotes.create("origin", _UNREACHABLE)

    with pytest.raises(RuntimeError, match=_MARKER):
        Pygit2Repository(str(repo_path)).fetch("origin")


def test_a_remote_added_later_brings_in_the_ssh_command_its_url_includes(
    ssh_command_for_the_remote, repo_path
):
    repo = Pygit2Repository(str(repo_path))
    repo.is_dirty()
    pygit2.Repository(str(repo_path)).remotes.create("origin", _UNREACHABLE)

    with pytest.raises(RuntimeError, match=_MARKER):
        repo.fetch("origin")
