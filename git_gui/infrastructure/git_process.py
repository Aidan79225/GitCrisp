from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from typing import Any

from git_gui.resources import subprocess_kwargs


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
