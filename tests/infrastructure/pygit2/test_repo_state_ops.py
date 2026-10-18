"""RepoStateOps mixin — merge state files and identity writes."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pygit2
import pytest


def test_get_merge_msg_reads_utf8_whatever_the_locale(repo_path, repo_impl):
    # git writes MERGE_MSG as UTF-8. These bytes are undecodable in cp1252 and
    # cp950, the ANSI code pages a Windows open() would otherwise fall back to.
    message = "Merge branch '功能'\n\n#Conflicts:\n#\tŁódź.txt\n"
    merge_msg = Path(pygit2.Repository(str(repo_path)).path) / "MERGE_MSG"
    merge_msg.write_bytes(message.encode("utf-8"))

    assert repo_impl.get_merge_msg() == message


@pytest.mark.skipif(sys.platform != "win32", reason="only Windows opens console windows")
def test_set_identity_runs_git_without_a_console_window(repo_impl, monkeypatch):
    creationflags: list[int] = []
    real_run = subprocess.run

    def recording_run(*args, **kwargs):
        creationflags.append(kwargs.get("creationflags", 0))
        return real_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", recording_run)

    repo_impl.set_identity("Ada", "ada@example.com", global_=False)

    assert creationflags
    assert all(flags & subprocess.CREATE_NO_WINDOW for flags in creationflags)
