from pathlib import Path
import pygit2
from git_gui.infrastructure.pygit2_repo import Pygit2Repository


def _seed(repo_path: Path) -> Pygit2Repository:
    impl = Pygit2Repository(str(repo_path))
    (repo_path / "a.txt").write_text("original\n")
    impl.stage(["a.txt"])
    impl.commit("seed")
    return impl


def test_discard_modified_file_reverts_to_head(repo_path):
    impl = _seed(repo_path)
    (repo_path / "a.txt").write_text("modified\n")
    impl.discard_file("a.txt")
    assert (repo_path / "a.txt").read_text() == "original\n"


def test_discard_deleted_file_restores(repo_path):
    impl = _seed(repo_path)
    (repo_path / "a.txt").unlink()
    impl.discard_file("a.txt")
    assert (repo_path / "a.txt").read_text() == "original\n"


def test_discard_untracked_file_unlinks(repo_path):
    impl = _seed(repo_path)
    (repo_path / "new.txt").write_text("hello\n")
    impl.discard_file("new.txt")
    assert not (repo_path / "new.txt").exists()


def test_discard_staged_add_unstages_and_unlinks(repo_path):
    impl = _seed(repo_path)
    (repo_path / "added.txt").write_text("staged add\n")
    impl.stage(["added.txt"])
    impl.discard_file("added.txt")
    assert not (repo_path / "added.txt").exists()
    assert "added.txt" not in [e.path for e in impl._repo.index]


def test_discard_modified_with_staged_changes_fully_resets(repo_path):
    impl = _seed(repo_path)
    (repo_path / "a.txt").write_text("staged change\n")
    impl.stage(["a.txt"])
    (repo_path / "a.txt").write_text("further unstaged\n")
    impl.discard_file("a.txt")
    assert (repo_path / "a.txt").read_text() == "original\n"
    head_commit = impl._repo.head.peel(pygit2.Commit)
    head_blob_id = head_commit.tree["a.txt"].id
    assert impl._repo.index["a.txt"].id == head_blob_id


def test_discard_hunk_reverts_only_that_hunk(repo_path):
    impl = Pygit2Repository(str(repo_path))
    lines = [f"line {i}\n" for i in range(1, 21)]
    (repo_path / "multi.txt").write_text("".join(lines))
    impl.stage(["multi.txt"])
    impl.commit("seed multi")

    lines[1] = "CHANGED line 2\n"
    lines[17] = "CHANGED line 18\n"
    (repo_path / "multi.txt").write_text("".join(lines))

    from git_gui.domain.entities import WORKING_TREE_OID
    hunks = impl.get_file_diff(WORKING_TREE_OID, "multi.txt")
    assert len(hunks) == 2

    impl.discard_hunk("multi.txt", hunks[0].header)

    text = (repo_path / "multi.txt").read_text()
    assert "line 2\n" in text
    assert "CHANGED line 2" not in text
    assert "CHANGED line 18\n" in text
