import os
import subprocess
import sys
from pathlib import Path
from typing import Protocol

# Project root when running from source
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_resource_path(relative: str) -> Path:
    """Resolve a path relative to the project root or PyInstaller bundle."""
    if getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS) / relative
    return _PROJECT_ROOT / relative


def subprocess_kwargs() -> dict:
    """Extra kwargs for subprocess calls to suppress console windows on Windows."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


_ACCEPT_NEW_SSH_COMMAND = "ssh -o StrictHostKeyChecking=accept-new"
_USER_SSH_VARIABLES = ("GIT_SSH_COMMAND", "GIT_SSH")
_USER_SSH_CONFIG_KEY = "core.sshCommand"


class GitConfig(Protocol):
    """The part of a git config `git_ssh_env` reads; pygit2's ``Config`` fits."""

    def __contains__(self, key: str, /) -> bool: ...


def git_ssh_env(
    base: dict[str, str] | None = None, *, config: GitConfig | None = None
) -> dict[str, str]:
    """Environment for git subprocesses, which run from a GUI that can answer no prompt.

    Our git calls run from a GUI without a TTY, so OpenSSH's interactive
    "Are you sure you want to continue connecting?" prompt for an unknown host
    can never be answered — the command just fails the first time we fetch from
    a new server. Setting ``StrictHostKeyChecking=accept-new`` makes OpenSSH
    auto-trust a host on first contact (recording it in ``known_hosts``) while
    still refusing a *changed* key, so protection against a man-in-the-middle is
    preserved.

    It is set only when the user has chosen no SSH client of their own: git
    ranks ``GIT_SSH_COMMAND`` above both ``core.sshCommand`` and ``GIT_SSH``, so
    setting it would silently replace either. Pass the repository's ``config``
    so a ``core.sshCommand`` there is seen.

    Git's own credential prompt is turned off for the same reason: started from
    a terminal, git would ask for a username there and wait while the GUI shows
    nothing. With ``GIT_TERMINAL_PROMPT=0`` it fails at once; credential
    helpers and askpass programs still run.

    Pass ``base`` to extend an existing environment dict; otherwise the current
    process environment is copied.
    """
    env = dict(base) if base is not None else os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    if not _user_chose_ssh_client(env, config):
        env["GIT_SSH_COMMAND"] = _ACCEPT_NEW_SSH_COMMAND
    return env


def _user_chose_ssh_client(env: dict[str, str], config: GitConfig | None) -> bool:
    if any(name in env for name in _USER_SSH_VARIABLES):
        return True
    return config is not None and _USER_SSH_CONFIG_KEY in config
