from pathlib import Path

import pygit2
import pytest

from git_gui.domain.entities import FileDelta, FileStatus, StagingState
from git_gui.infrastructure.pygit2 import Pygit2Repository


@pytest.fixture
def multi_hunk_repo(repo_path) -> tuple[Pygit2Repository, Path]:
    """Create a repo with a file that has two separate unstaged hunks."""
    impl = Pygit2Repository(str(repo_path))
    # Write a file with several lines, commit it
    lines = [f"line {i}\n" for i in range(1, 21)]
    (repo_path / "multi.txt").write_text("".join(lines))
    impl.stage(["multi.txt"])
    impl.commit("add multi.txt")

    # Modify two separate regions to create two hunks
    lines[1] = "CHANGED line 2\n"  # near top
    lines[17] = "CHANGED line 18\n"  # near bottom
    (repo_path / "multi.txt").write_text("".join(lines))
    return impl, repo_path


def test_stage_hunk_stages_only_one_hunk(multi_hunk_repo):
    impl, path = multi_hunk_repo
    # Get the unstaged diff — should have 2 hunks
    hunks = impl.get_file_diff("WORKING_TREE", "multi.txt")
    assert len(hunks) == 2

    # Stage only the first hunk
    impl.stage_hunk("multi.txt", hunks[0].header)

    # Now staged diff should have 1 hunk (the one we staged)
    staged = impl.get_staged_diff("multi.txt")
    assert len(staged) == 1
    assert "CHANGED line 2" in "".join(c for _, c in staged[0].lines)

    # Unstaged diff should still have 1 hunk (the one we didn't stage)
    remaining = impl.get_file_diff("WORKING_TREE", "multi.txt")
    assert len(remaining) == 1
    assert "CHANGED line 18" in "".join(c for _, c in remaining[0].lines)


def test_staging_a_hunk_writes_the_repositorys_own_index(
    multi_hunk_repo, tmp_path_factory, monkeypatch
):
    """Started from a commit hook, the app inherits GIT_INDEX_FILE, and
    `git apply --cached` patched that index instead: "does not exist in index"."""
    impl, _path = multi_hunk_repo
    other = pygit2.init_repository(str(tmp_path_factory.mktemp("hooked")))
    other.index.write()
    monkeypatch.setenv("GIT_INDEX_FILE", str(Path(other.path) / "index"))
    hunks = impl.get_file_diff("WORKING_TREE", "multi.txt")

    impl.stage_hunk("multi.txt", hunks[0].header)

    assert len(impl.get_staged_diff("multi.txt")) == 1


def test_unstage_hunk_unstages_only_one_hunk(multi_hunk_repo):
    impl, path = multi_hunk_repo
    # Stage the whole file first
    impl.stage(["multi.txt"])

    # Staged diff should have 2 hunks
    staged = impl.get_staged_diff("multi.txt")
    assert len(staged) == 2

    # Unstage only the first hunk
    impl.unstage_hunk("multi.txt", staged[0].header)

    # Staged should now have 1 hunk
    staged_after = impl.get_staged_diff("multi.txt")
    assert len(staged_after) == 1
    assert "CHANGED line 18" in "".join(c for _, c in staged_after[0].lines)

    # Unstaged should have 1 hunk (the one we unstaged)
    unstaged = impl.get_file_diff("WORKING_TREE", "multi.txt")
    assert len(unstaged) == 1
    assert "CHANGED line 2" in "".join(c for _, c in unstaged[0].lines)


def _edited_repo(repo_path: Path, committed: bytes, edited: bytes) -> Pygit2Repository:
    """f.txt committed with *committed*, then rewritten as *edited*, byte for byte."""
    impl = Pygit2Repository(str(repo_path))
    impl._repo.config["core.autocrlf"] = False
    (repo_path / "f.txt").write_bytes(committed)
    impl.stage(["f.txt"])
    impl.commit("seed f.txt")
    (repo_path / "f.txt").write_bytes(edited)
    return impl


def _only_hunk_header(impl: Pygit2Repository) -> str:
    [hunk] = impl.get_file_diff("WORKING_TREE", "f.txt")
    return hunk.header


def _staged_bytes(impl: Pygit2Repository) -> bytes:
    impl._repo.index.read()
    return impl._repo[impl._repo.index["f.txt"].id].data


def test_staging_a_hunk_keeps_bytes_that_are_not_utf8(repo_path):
    impl = _edited_repo(repo_path, b"caf\xe9\nline2\nline3\n", b"caf\xe9\nLINE2\nline3\n")

    impl.stage_hunk("f.txt", _only_hunk_header(impl))

    assert _staged_bytes(impl) == b"caf\xe9\nLINE2\nline3\n"


def test_staging_an_added_non_utf8_line_stages_the_bytes_on_disk(repo_path):
    impl = _edited_repo(repo_path, b"a\nb\nc\n", b"a\ncaf\xe9\nc\n")

    impl.stage_hunk("f.txt", _only_hunk_header(impl))

    assert _staged_bytes(impl) == b"a\ncaf\xe9\nc\n"


def test_discarding_a_hunk_restores_bytes_that_are_not_utf8(repo_path):
    impl = _edited_repo(repo_path, b"caf\xe9\nb\n", b"cafe\nb\n")

    impl.discard_hunk("f.txt", _only_hunk_header(impl))

    assert (repo_path / "f.txt").read_bytes() == b"caf\xe9\nb\n"


@pytest.mark.parametrize(
    ("committed", "edited"),
    [
        (b"a\nb", b"a\nc"),
        (b"a\nb\n", b"a\nc"),
        (b"a\nb", b"a\nb\nc\n"),
        (b"a\nb\nc", b"A\nb\nc"),
    ],
    ids=["neither-side-ends-in-newline", "newline-removed", "newline-added", "context-at-eof"],
)
def test_staging_a_hunk_at_a_missing_final_newline_stages_the_file_as_edited(
    repo_path, committed, edited
):
    impl = _edited_repo(repo_path, committed, edited)

    impl.stage_hunk("f.txt", _only_hunk_header(impl))

    assert _staged_bytes(impl) == edited


def test_unstaging_a_hunk_at_a_missing_final_newline_restores_head(repo_path):
    impl = _edited_repo(repo_path, b"a\nb", b"a\nc")
    impl.stage(["f.txt"])
    [staged] = impl.get_staged_diff("f.txt")

    impl.unstage_hunk("f.txt", staged.header)

    assert _staged_bytes(impl) == b"a\nb"


def test_discarding_a_hunk_at_a_missing_final_newline_restores_head(repo_path):
    impl = _edited_repo(repo_path, b"a\nb", b"a\nb\nc\n")

    impl.discard_hunk("f.txt", _only_hunk_header(impl))

    assert (repo_path / "f.txt").read_bytes() == b"a\nb"


def _deleted_executable(repo_path: Path) -> Pygit2Repository:
    """d.txt committed as an executable, then deleted from the working tree."""
    impl = Pygit2Repository(str(repo_path))
    blob = impl._repo.create_blob(b"a\nb\n")
    impl._repo.index.add(pygit2.IndexEntry("d.txt", blob, pygit2.GIT_FILEMODE_BLOB_EXECUTABLE))
    impl._repo.index.write()
    impl.commit("seed d.txt")
    return impl


def test_staging_the_hunk_of_a_deleted_file_stages_the_deletion(repo_path):
    impl = _deleted_executable(repo_path)
    [hunk] = impl.get_file_diff("WORKING_TREE", "d.txt")

    impl.stage_hunk("d.txt", hunk.header)

    assert impl.get_working_tree() == [FileStatus("d.txt", StagingState.STAGED, FileDelta.DELETED)]


def test_unstaging_the_hunk_of_a_staged_deletion_puts_the_file_back_with_its_mode(repo_path):
    impl = _deleted_executable(repo_path)
    impl.stage(["d.txt"])
    [hunk] = impl.get_staged_diff("d.txt")

    impl.unstage_hunk("d.txt", hunk.header)

    head_entry = impl._repo.head.peel(pygit2.Commit).tree["d.txt"]
    impl._repo.index.read()
    restored = impl._repo.index["d.txt"]
    assert (restored.id, restored.mode) == (head_entry.id, head_entry.filemode)
