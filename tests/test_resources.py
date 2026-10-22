import sys
from pathlib import Path

import pygit2

from git_gui.resources import get_resource_path, git_ssh_env


def test_get_resource_path_normal():
    """In normal (non-frozen) mode, resolves relative to project root."""
    result = get_resource_path("arts")
    assert result.name == "arts"
    assert result.parent == Path(__file__).resolve().parent.parent


def test_get_resource_path_frozen(monkeypatch):
    """In PyInstaller frozen mode, resolves relative to _MEIPASS."""
    fake_meipass = "/tmp/fake_meipass"
    monkeypatch.setattr(sys, "_MEIPASS", fake_meipass, raising=False)
    result = get_resource_path("arts")
    assert result == Path(fake_meipass) / "arts"


def test_git_ssh_env_sets_accept_new(monkeypatch):
    """Without a preconfigured GIT_SSH_COMMAND, accept-new is enabled so that a
    first-time SSH connection to an unknown host trusts the key instead of
    failing on an unanswerable interactive prompt."""
    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    monkeypatch.delenv("GIT_SSH", raising=False)
    env = git_ssh_env()
    assert "StrictHostKeyChecking=accept-new" in env["GIT_SSH_COMMAND"]


def test_git_ssh_env_respects_existing_command(monkeypatch):
    """A GIT_SSH_COMMAND the user already configured is left untouched."""
    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -i /custom/key")
    env = git_ssh_env()
    assert env["GIT_SSH_COMMAND"] == "ssh -i /custom/key"


def test_git_ssh_env_extends_base_without_mutating():
    """Passing a base dict extends it (with GIT_SSH_COMMAND) without mutating
    the caller's dict."""
    base = {"GIT_DIR": "/repo/.git"}
    env = git_ssh_env(base)
    assert env["GIT_DIR"] == "/repo/.git"
    assert "StrictHostKeyChecking=accept-new" in env["GIT_SSH_COMMAND"]
    assert "GIT_SSH_COMMAND" not in base


def test_git_ssh_env_leaves_the_users_git_ssh_in_charge():
    """git ranks GIT_SSH_COMMAND above GIT_SSH, so adding it would replace
    the client the user chose (PuTTY's plink, say)."""
    env = git_ssh_env({"GIT_SSH": "plink.exe"})
    assert "GIT_SSH_COMMAND" not in env


def test_git_ssh_env_leaves_a_configured_core_ssh_command_in_charge(tmp_path):
    """git ranks GIT_SSH_COMMAND above core.sshCommand, so adding it would
    replace the command the repository is configured to use."""
    repo = pygit2.init_repository(str(tmp_path))
    repo.config["core.sshCommand"] = "ssh -i ~/.ssh/id_work -o IdentitiesOnly=yes"
    env = git_ssh_env({}, config=repo.config)
    assert "GIT_SSH_COMMAND" not in env


def test_git_ssh_env_adds_accept_new_when_the_config_names_no_ssh_command():
    env = git_ssh_env({}, config={"user.name": "T"})
    assert "StrictHostKeyChecking=accept-new" in env["GIT_SSH_COMMAND"]


def test_git_ssh_env_turns_off_git_terminal_prompts():
    """Started from a terminal, git would ask for a username on it and wait
    there with the GUI showing nothing; with prompts off it fails at once."""
    assert git_ssh_env({})["GIT_TERMINAL_PROMPT"] == "0"


def test_git_ssh_env_keeps_a_terminal_prompt_setting_the_user_made():
    assert git_ssh_env({"GIT_TERMINAL_PROMPT": "1"})["GIT_TERMINAL_PROMPT"] == "1"
