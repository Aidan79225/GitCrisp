from __future__ import annotations

import itertools
import os
import re
import shutil
import stat
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from git_gui.infrastructure.git_process import (
    git_popen_kwargs,
    isolated_git_env,
    kill_git_tree,
    run_git,
)
from git_gui.resources import git_ssh_env


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

# Windows refuses to delete a file while another process holds it open: a
# helper the cancel has just killed, or a virus scanner reading a fresh pack.
# Such a handle closes within moments, so a removal waits this long between tries.
_IN_USE_RETRY_SECONDS = (0.1, 0.3, 1.0)


class CloneCancelled(Exception):
    """The clone was stopped on request and what it wrote was removed.

    ``cleanup_error`` says why, when some of it could not be removed and is
    still in the destination.
    """

    def __init__(self, message: str, cleanup_error: OSError | None = None) -> None:
        super().__init__(message)
        self.cleanup_error = cleanup_error


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
    # An inherited GIT_DIR would get the clone's URL as that repository's origin.
    env = isolated_git_env()
    if run_git(["git", "init", "--quiet", "--", str(dest)], cwd=".", env=env).returncode != 0:
        return False
    probe = f"--git-dir={dest / '.git'}"
    run_git(["git", probe, "config", "remote.origin.url", url], cwd=".", env=env)
    return run_git(["git", probe, "config", "--get", key], cwd=".", env=env).returncode == 0


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
        # "--": a URL or folder that starts with "-" is still a URL or folder, not an option.
        ["git", "clone", "--progress", "--recurse-submodules", "--", url, dest],
        # Nothing reads stdout, and git writes a line there per submodule: a
        # pipe would fill up and block git while we wait for stderr to close.
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        # git_ssh_env asks _CloneConfig, which probes dest with a throwaway
        # repository, only when the environment names no ssh client.
        env=git_ssh_env(isolated_git_env(), config=_CloneConfig(url, dest)),
        **git_popen_kwargs(),
    )
    _stop_when_cancelled(proc, cancelled)
    messages = _read_messages(proc.stderr, on_progress)

    proc.wait()
    if cancelled.is_set():
        message = f"Clone of {url} was cancelled"
        try:
            destination.restore()
        except OSError as error:
            # Raised as the cancel it is: whoever cancelled is no longer waiting for a failure.
            raise CloneCancelled(message, cleanup_error=error) from error
        raise CloneCancelled(message)
    if proc.returncode != 0:
        destination.remove_created_parents()  # git removes only the destination itself.
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
                # Forced: what the clone wrote is removed next, locks and all.
                kill_git_tree(proc, force=True)
                return

    threading.Thread(target=watch, name="clone-cancel-watcher", daemon=True).start()


class _Destination:
    """The clone's destination as it was before git ran, so a cancel can put it back."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._existed = path.exists()
        self._was_free = _is_free_for_a_clone(path)
        # git creates the folders on the way to a destination that is not there yet.
        self._new_parents = list(itertools.takewhile(lambda p: not p.exists(), path.parents))

    def restore(self) -> None:
        if not self._was_free:
            return  # git refuses a folder with files in it, so none of them are the clone's.
        if not self._existed:
            _remove(self._path)
            self.remove_created_parents()
        elif self._path.is_dir():
            for entry in self._path.iterdir():
                _remove(entry)

    def remove_created_parents(self) -> None:
        """Remove the folders git created on the way to the destination, nearest first.

        Only empty ones go: a folder that holds anything else by now, such as a
        clone git kept after its checkout failed, stays, and so do those above it.
        """
        for parent in self._new_parents:
            try:
                parent.rmdir()
            except FileNotFoundError:
                continue  # git stopped before it got this far down.
            except OSError:
                return


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, onexc=_make_writable_and_retry)
    elif path.exists() or path.is_symlink():
        # No chmod here: it would follow a checked-out symlink out of the clone.
        _retry_while_in_use(path.unlink)


def _make_writable_and_retry(
    remove: Callable[[str], object], path: str, _error: BaseException
) -> None:
    # git writes its packs read-only, and Windows refuses to delete a read-only file.
    os.chmod(path, stat.S_IWRITE)
    _retry_while_in_use(lambda: remove(path))


def _retry_while_in_use(remove: Callable[[], object]) -> None:
    for delay in _IN_USE_RETRY_SECONDS:
        try:
            remove()
            return
        except PermissionError:
            time.sleep(delay)
    remove()


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
