import sys
from pathlib import Path

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
