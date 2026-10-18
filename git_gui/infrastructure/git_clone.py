from __future__ import annotations

import re
import shutil
import subprocess
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from git_gui.infrastructure.git_process import git_popen_kwargs, run_git
from git_gui.resources import git_ssh_env


@dataclass
class CloneProgress:
    phase: str  # e.g. "Receiving objects", "Resolving deltas"
    percent: int  # 0-100


_PROGRESS_RE = re.compile(r"(.+?):\s+(\d+)%")

# git states why a clone failed at the end; a recursive clone can print a line
# per submodule before that, so only the tail is kept for the error message.
_KEPT_MESSAGE_LINES = 20


class _CloneConfig:
    """The git config the repository cloned from ``url`` into ``dest`` will read.

    git evaluates conditional includes (``includeIf "gitdir:..."``,
    ``"hasconfig:remote.*.url:..."``) against the repository it runs in, so the
    user's config files read on their own miss what such a section sets for
    this clone. Only git, asked from a repository at ``dest`` with that remote,
    answers as the clone will; that probe repository is removed again so the
    clone finds the destination as the user left it.
    """

    def __init__(self, url: str, dest: str) -> None:
        self._url = url
        self._dest = Path(dest)

    def __contains__(self, key: str) -> bool:
        if not _is_free_for_a_clone(self._dest):
            return False  # git clone refuses this destination before it connects.
        created = not self._dest.exists()
        try:
            return _probe_has_config(self._dest, self._url, key)
        finally:
            _remove_probe(self._dest, created)


def _is_free_for_a_clone(dest: Path) -> bool:
    return not dest.exists() or (dest.is_dir() and not any(dest.iterdir()))


def _probe_has_config(dest: Path, url: str, key: str) -> bool:
    if run_git(["git", "init", "--quiet", str(dest)], cwd=".").returncode != 0:
        return False
    run_git(["git", "-C", str(dest), "config", "remote.origin.url", url], cwd=".")
    return run_git(["git", "-C", str(dest), "config", "--get", key], cwd=".").returncode == 0


def _remove_probe(dest: Path, created: bool) -> None:
    probe_git_dir = dest / ".git"
    if probe_git_dir.exists():
        shutil.rmtree(probe_git_dir)
    if created and dest.exists():
        dest.rmdir()


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
        env=git_ssh_env(config=_CloneConfig(url, dest)),
        **git_popen_kwargs(),
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
