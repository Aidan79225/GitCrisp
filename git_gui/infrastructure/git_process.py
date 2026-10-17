from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence

from git_gui.resources import subprocess_kwargs


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
        **subprocess_kwargs(),
    )
