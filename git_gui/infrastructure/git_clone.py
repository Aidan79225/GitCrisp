from __future__ import annotations

import re
import subprocess
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import IO

from git_gui.resources import git_ssh_env, subprocess_kwargs


@dataclass
class CloneProgress:
    phase: str  # e.g. "Receiving objects", "Resolving deltas"
    percent: int  # 0-100


_PROGRESS_RE = re.compile(r"(.+?):\s+(\d+)%")

# git states why a clone failed at the end; a recursive clone can print a line
# per submodule before that, so only the tail is kept for the error message.
_KEPT_MESSAGE_LINES = 20


def clone_repo(
    url: str,
    dest: str,
    on_progress: Callable[[CloneProgress], None] | None = None,
) -> None:
    """Clone a git repo with progress reporting.

    Runs ``git clone --progress`` and parses stderr for progress updates.
    Raises ``RuntimeError`` carrying git's own explanation on failure.
    """
    proc = subprocess.Popen(
        ["git", "clone", "--progress", "--recurse-submodules", url, dest],
        # Nothing reads stdout, and git writes a line there per submodule: a
        # pipe would fill up and block git while we wait for stderr to close.
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=git_ssh_env(),
        **subprocess_kwargs(),
    )

    messages: deque[str] = deque(maxlen=_KEPT_MESSAGE_LINES)
    for line in filter(None, _stderr_lines(proc.stderr)):
        progress = _parse_progress(line)
        if progress is None:
            messages.append(line)
        elif on_progress:
            on_progress(progress)

    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("\n".join(messages) or f"git clone exited with code {proc.returncode}")


def _stderr_lines(stream: IO[bytes]) -> Iterator[str]:
    """Yield git's stderr line by line as it arrives.

    A carriage return ends a line too: git redraws its progress line in place.
    """
    buf = b""
    while chunk := stream.read(1):
        if chunk in (b"\r", b"\n"):
            yield buf.decode("utf-8", errors="replace").strip()
            buf = b""
        else:
            buf += chunk
    yield buf.decode("utf-8", errors="replace").strip()


def _parse_progress(line: str) -> CloneProgress | None:
    match = _PROGRESS_RE.search(line)
    if match is None:
        return None
    return CloneProgress(phase=match.group(1).strip(), percent=int(match.group(2)))
