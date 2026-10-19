"""A discard that cannot rewrite the file fails without unstaging it.

On Windows a file another program holds open cannot be deleted or replaced;
the discard must then leave the staged change and the work tree as they were,
not reset the index and stop there.
"""

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pygit2
import pytest

from git_gui.infrastructure.pygit2 import Pygit2Repository


@contextmanager
def _undeletable(path: Path) -> Iterator[None]:
    if sys.platform == "win32":
        # Python opens files without FILE_SHARE_DELETE, so while this handle
        # is open nothing can delete or replace the file.
        with open(path, "rb"):
            yield
        return
    if os.geteuid() == 0:
        pytest.skip("root can delete files from a read-only folder")
    folder = path.parent
    mode = folder.stat().st_mode
    folder.chmod(mode & ~0o222)
    try:
        yield
    finally:
        folder.chmod(mode)


def _on_disk_index(repo_path: Path) -> pygit2.Index:
    return pygit2.Repository(str(repo_path)).index


def test_a_discard_that_cannot_replace_the_file_keeps_its_staged_change(repo_path):
    impl = Pygit2Repository(str(repo_path))
    (repo_path / "docs").mkdir()
    doc = repo_path / "docs" / "a.txt"
    doc.write_text("original\n")
    impl.stage(["docs/a.txt"])
    impl.commit("seed docs/a.txt")
    doc.write_text("staged\n")
    impl.stage(["docs/a.txt"])
    doc.write_text("unstaged\n")
    staged_blob = _on_disk_index(repo_path)["docs/a.txt"].id

    with _undeletable(doc), pytest.raises(RuntimeError, match="docs/a.txt"):
        impl.discard_file("docs/a.txt")

    assert _on_disk_index(repo_path)["docs/a.txt"].id == staged_blob
    assert doc.read_text() == "unstaged\n"


def test_a_discard_that_cannot_delete_a_new_file_keeps_it_staged(repo_path):
    impl = Pygit2Repository(str(repo_path))
    (repo_path / "docs").mkdir()
    new = repo_path / "docs" / "new.txt"
    new.write_text("new\n")
    impl.stage(["docs/new.txt"])

    with _undeletable(new), pytest.raises(OSError):
        impl.discard_file("docs/new.txt")

    assert "docs/new.txt" in _on_disk_index(repo_path)
    assert new.exists()
