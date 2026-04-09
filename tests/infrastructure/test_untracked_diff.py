from pathlib import Path
from git_gui.infrastructure.pygit2_repo import Pygit2Repository
from git_gui.domain.entities import WORKING_TREE_OID


def _init(repo_path: Path) -> Pygit2Repository:
    impl = Pygit2Repository(str(repo_path))
    (repo_path / "seed.txt").write_text("seed\n")
    impl.stage(["seed.txt"])
    impl.commit("seed")
    return impl


def test_untracked_text_file_has_synthetic_hunk(repo_path):
    impl = _init(repo_path)
    (repo_path / "new.txt").write_text("alpha\nbeta\ngamma\n")
    hunks = impl.get_file_diff(WORKING_TREE_OID, "new.txt")
    assert len(hunks) == 1
    assert hunks[0].header.startswith("@@ -0,0 +1,3")
    origins = [o for o, _ in hunks[0].lines]
    assert origins == ["+", "+", "+"]
    contents = [c.rstrip("\n") for _, c in hunks[0].lines]
    assert contents == ["alpha", "beta", "gamma"]


def test_untracked_binary_file_shows_placeholder(repo_path):
    impl = _init(repo_path)
    (repo_path / "blob.bin").write_bytes(b"abc\x00def\x00ghi")
    hunks = impl.get_file_diff(WORKING_TREE_OID, "blob.bin")
    assert len(hunks) == 1
    assert hunks[0].lines[0][0] == "+"
    assert "Binary file" in hunks[0].lines[0][1]


def test_untracked_large_file_shows_placeholder(repo_path):
    impl = _init(repo_path)
    big = "x\n" * 6000
    (repo_path / "big.txt").write_text(big)
    hunks = impl.get_file_diff(WORKING_TREE_OID, "big.txt")
    assert len(hunks) == 1
    assert "Large file" in hunks[0].lines[0][1]
