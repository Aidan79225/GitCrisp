"""RepoStateOps mixin — merge state files and identity writes."""

from __future__ import annotations

from pathlib import Path

import pygit2


def test_get_merge_msg_reads_utf8_whatever_the_locale(repo_path, repo_impl):
    # git writes MERGE_MSG as UTF-8. These bytes are undecodable in cp1252 and
    # cp950, the ANSI code pages a Windows open() would otherwise fall back to.
    message = "Merge branch '功能'\n\n#Conflicts:\n#\tŁódź.txt\n"
    merge_msg = Path(pygit2.Repository(str(repo_path)).path) / "MERGE_MSG"
    merge_msg.write_bytes(message.encode("utf-8"))

    assert repo_impl.get_merge_msg() == message
