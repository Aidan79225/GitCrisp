# git_gui/infrastructure/git_clone.py
from __future__ import annotations
import re
import subprocess
import threading
from dataclasses import dataclass
from typing import Callable

from git_gui.resources import subprocess_kwargs


@dataclass
class CloneProgress:
    phase: str    # e.g. "Receiving objects", "Resolving deltas"
    percent: int  # 0-100


_PROGRESS_RE = re.compile(r"(.+?):\s+(\d+)%")


def clone_repo(
    url: str,
    dest: str,
    on_progress: Callable[[CloneProgress], None] | None = None,
) -> None:
    """Clone a git repo with progress reporting.

    Runs ``git clone --progress`` and parses stderr for progress updates.
    Raises ``subprocess.CalledProcessError`` on failure.
    """
    proc = subprocess.Popen(
        ["git", "clone", "--progress", "--recurse-submodules", url, dest],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **subprocess_kwargs(),
    )

    # git clone writes progress to stderr
    buf = b""
    while True:
        chunk = proc.stderr.read(1)
        if not chunk:
            break
        if chunk in (b"\r", b"\n"):
            line = buf.decode("utf-8", errors="replace").strip()
            buf = b""
            if line and on_progress:
                m = _PROGRESS_RE.search(line)
                if m:
                    on_progress(CloneProgress(
                        phase=m.group(1).strip(),
                        percent=int(m.group(2)),
                    ))
        else:
            buf += chunk

    proc.wait()
    if proc.returncode != 0:
        stderr_output = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
        raise subprocess.CalledProcessError(
            proc.returncode, ["git", "clone", "--recurse-submodules", url, dest],
            output=b"", stderr=stderr_output.encode(),
        )
