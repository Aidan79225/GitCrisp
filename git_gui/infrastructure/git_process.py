from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from typing import Any

from git_gui.resources import subprocess_kwargs

# Variables that aim git at a repository other than the one it is pointed at;
# GIT_CONFIG does the same for `git config`. The GIT_CONFIG_* variables that add
# settings stay: the user set them for every git command.
_OTHER_REPOSITORY_VARIABLES = frozenset(
    {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_COMMON_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_CONFIG",
    }
)


def isolated_git_env() -> dict[str, str]:
    """This process's environment, minus what would aim git at another repository.

    Started from a shell that exports them (a dotfiles setup, a git hook), git
    ranks these variables above both ``-C`` and the folder it runs in: a clone
    checks out into the GIT_WORK_TREE folder, or writes the index and objects
    that GIT_INDEX_FILE and GIT_OBJECT_DIRECTORY name.
    """
    return {
        name: value for name, value in os.environ.items() if name not in _OTHER_REPOSITORY_VARIABLES
    }


def git_popen_kwargs() -> dict[str, Any]:
    """Popen kwargs for a git process started from the GUI.

    On POSIX git gets a session of its own, so it has no controlling terminal.
    Launched from a terminal, ssh would otherwise ask for a key's passphrase
    on it and git would wait there while the GUI shows nothing; without one,
    ssh asks through SSH_ASKPASS or fails at once.
    """
    kwargs = subprocess_kwargs()
    if os.name == "posix":
        kwargs["start_new_session"] = True
    return kwargs


def run_git(
    argv: Sequence[str],
    *,
    cwd: str,
    env: Mapping[str, str] | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a git command to completion and capture its output as text.

    git writes paths, ref names and commit subjects as UTF-8 whatever the
    locale's code page is. Decoded with the locale (cp950, cp1252) instead,
    one such byte fails subprocess's reader thread and the whole stream comes
    back as None, taking git's explanation with it.
    """
    return subprocess.run(
        list(argv),
        cwd=cwd,
        env=env,
        check=check,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        **git_popen_kwargs(),
    )


def git_run_dir(work_tree: str | None, git_dir: str | None) -> str:
    """The directory to start git in: the working tree, or a bare repository's gitdir."""
    run_dir = work_tree or git_dir
    if run_dir is None:
        raise ValueError("git needs a working tree or a gitdir to run in")
    return run_dir


def pinned_git_env(git_dir: str | None, work_tree: str | None) -> dict[str, str]:
    """This process's environment with git pinned to `git_dir`, when one is given.

    Left to discover the repository from its working directory, git walks up
    from a submodule whose `.git` link is missing and reads the parent instead.
    A bare repository has no working tree to name, so it gets GIT_DIR alone.
    """
    env = os.environ.copy()
    if git_dir is not None:
        env["GIT_DIR"] = git_dir
        if work_tree:
            env["GIT_WORK_TREE"] = work_tree
    return env
