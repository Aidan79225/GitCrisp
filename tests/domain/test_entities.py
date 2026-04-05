from datetime import datetime, timezone
from git_gui.domain.entities import Commit, Branch, Stash, FileStatus, Hunk, Tag


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


def test_tag_lightweight():
    tag = Tag(name="v1.0.0", target_oid="abc123", is_annotated=False,
              message=None, tagger=None, timestamp=None)
    assert tag.name == "v1.0.0"
    assert tag.target_oid == "abc123"
    assert tag.is_annotated is False
    assert tag.message is None


def test_tag_annotated():
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    tag = Tag(name="v2.0.0", target_oid="def456", is_annotated=True,
              message="Release 2.0", tagger="Alice <alice@example.com>", timestamp=ts)
    assert tag.is_annotated is True
    assert tag.message == "Release 2.0"
    assert tag.tagger == "Alice <alice@example.com>"
