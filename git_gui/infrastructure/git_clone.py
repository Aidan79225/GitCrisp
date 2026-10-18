from __future__ import annotations

import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from git_gui.infrastructure.git_process import git_popen_kwargs, run_git
from git_gui.resources import git_ssh_env, subprocess_kwargs


@dataclass
class CloneProgress:
    phase: str  # e.g. "Receiving objects", "Resolving deltas"
    percent: int  # 0-100


_PROGRESS_RE = re.compile(r"(.+?):\s+(\d+)%")

# git states why a clone failed at the end; a recursive clone can print a line
# per submodule before that, so only the tail is kept for the error message.
_KEPT_MESSAGE_LINES = 20

# How often the cancel watcher checks whether git ended by itself. It bounds
# only how long the watcher outlives git; a cancel is acted on at once.
_EXIT_POLL_SECONDS = 0.1


class CloneCancelled(Exception):
    """The clone was stopped on request and what it wrote was removed."""


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
    cancelled: threading.Event | None = None,
) -> None:
    """Clone a git repo with progress reporting.

    Runs ``git clone --progress`` and parses stderr for progress updates.
    Raises ``RuntimeError`` carrying git's own explanation on failure. Setting
    ``cancelled`` stops git and every process it started, removes what the
    clone wrote, and raises ``CloneCancelled``.
    """
    if cancelled is None:
        cancelled = threading.Event()
    destination = _Destination(Path(dest))
    proc = subprocess.Popen(
        ["git", "clone", "--progress", "--recurse-submodules", url, dest],
        # Nothing reads stdout, and git writes a line there per submodule: a
        # pipe would fill up and block git while we wait for stderr to close.
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=git_ssh_env(config=_CloneConfig(url, dest)),
        **git_popen_kwargs(),
    )
    _stop_when_cancelled(proc, cancelled)
    messages = _read_messages(proc.stderr, on_progress)

    proc.wait()
    if cancelled.is_set():
        destination.restore()
        raise CloneCancelled(f"Clone of {url} was cancelled")
    if proc.returncode != 0:
        raise RuntimeError("\n".join(messages) or f"git clone exited with code {proc.returncode}")


def _read_messages(
    stream: IO[bytes], on_progress: Callable[[CloneProgress], None] | None
) -> deque[str]:
    """Pass git's progress lines to ``on_progress`` and keep the last of the others."""
    messages: deque[str] = deque(maxlen=_KEPT_MESSAGE_LINES)
    for line in filter(None, _stderr_lines(stream)):
        progress = _parse_progress(line)
        if progress is None:
            messages.append(line)
        elif on_progress:
            on_progress(progress)
    return messages


def _stop_when_cancelled(proc: subprocess.Popen[bytes], cancelled: threading.Event) -> None:
    def watch() -> None:
        while proc.poll() is None:
            if cancelled.wait(_EXIT_POLL_SECONDS):
                _kill_process_tree(proc)
                return

    threading.Thread(target=watch, name="clone-cancel-watcher", daemon=True).start()


def _kill_process_tree(proc: subprocess.Popen[bytes]) -> None:
    """Stop git and the helpers it runs (ssh, git-remote-https, index-pack).

    The helpers hold git's stderr open, so stopping git alone would leave the
    clone reading from them until they gave up by themselves. On Windows the
    ``git`` on PATH is often a launcher, which makes even git proper a child.
    """
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **subprocess_kwargs(),
        )
    else:
        try:
            # git_popen_kwargs gives git a session, so its group is git and its helpers.
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # git ended by itself in the meantime.


class _Destination:
    """The clone's destination as it was before git ran, so a cancel can put it back."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._existed = path.exists()
        self._was_free = _is_free_for_a_clone(path)

    def restore(self) -> None:
        if not self._was_free:
            return  # git refuses a folder with files in it, so none of them are the clone's.
        if not self._existed:
            _remove(self._path)
        elif self._path.is_dir():
            for entry in self._path.iterdir():
                _remove(entry)


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, onexc=_make_writable_and_retry)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _make_writable_and_retry(
    remove: Callable[[str], object], path: str, _error: BaseException
) -> None:
    # git writes its packs read-only, and Windows refuses to delete a read-only file.
    os.chmod(path, stat.S_IWRITE)
    remove(path)


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
