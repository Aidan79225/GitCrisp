from datetime import datetime
from git_gui.domain.entities import Commit, Branch, Stash, FileStatus, Hunk


def test_commit_fields():
    c = Commit(
        oid="abc123",
        message="Initial commit",
        author="Alice <alice@example.com>",
        timestamp=datetime(2026, 1, 1, 12, 0),
        parents=[],
    )
    assert c.oid == "abc123"
    assert c.parents == []


def test_commit_with_parents():
    c = Commit(oid="def", message="Second", author="Bob", timestamp=datetime.now(), parents=["abc123"])
    assert c.parents == ["abc123"]


def test_branch_fields():
    b = Branch(name="main", is_remote=False, is_head=True, target_oid="abc123")
    assert b.is_head is True
    assert b.is_remote is False


def test_stash_fields():
    s = Stash(index=0, message="WIP: feature", oid="stash_oid")
    assert s.index == 0


def test_file_status_fields():
    f = FileStatus(path="src/main.py", status="staged", delta="modified")
    assert f.status == "staged"
    assert f.delta == "modified"


def test_hunk_fields():
    h = Hunk(header="@@ -1,3 +1,4 @@", lines=[("+", "new line\n"), (" ", "context\n")])
    assert h.header.startswith("@@")
    assert h.lines[0] == ("+", "new line\n")
