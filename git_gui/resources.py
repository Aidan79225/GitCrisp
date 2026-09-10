import os
import subprocess
import sys
from pathlib import Path

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


def git_ssh_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for git subprocesses so first-time SSH host-key checks don't fail.

    Our git calls run from a GUI without a TTY, so OpenSSH's interactive
    "Are you sure you want to continue connecting?" prompt for an unknown host
    can never be answered — the command just fails the first time we fetch from
    a new server. Setting ``StrictHostKeyChecking=accept-new`` makes OpenSSH
    auto-trust a host on first contact (recording it in ``known_hosts``) while
    still refusing a *changed* key, so protection against a man-in-the-middle is
    preserved. A ``GIT_SSH_COMMAND`` the user has already configured is left
    untouched.

    Pass ``base`` to extend an existing environment dict; otherwise the current
    process environment is copied.
    """
    env = dict(base) if base is not None else os.environ.copy()
    env.setdefault("GIT_SSH_COMMAND", "ssh -o StrictHostKeyChecking=accept-new")
    return env
