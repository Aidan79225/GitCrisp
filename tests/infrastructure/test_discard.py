from pathlib import Path
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
