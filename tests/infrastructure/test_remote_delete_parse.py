from git_gui.infrastructure.pygit2.remote_ops import _parse_porcelain_delete


def test_all_deleted_ok():
    stdout = (
        "To github.com:u/r.git\n"
        "-\t:refs/heads/feat-a\t[deleted]\n"
        "-\t:refs/heads/feat-b\t[deleted]\n"
        "Done\n"
    )
    results = _parse_porcelain_delete("origin", stdout, ["feat-a", "feat-b"])
    assert [(r.branch, r.ok) for r in results] == [
        ("origin/feat-a", True),
        ("origin/feat-b", True),
    ]


def test_mixed_ok_and_rejected():
    stdout = (
        "To github.com:u/r.git\n"
        "-\t:refs/heads/feat-a\t[deleted]\n"
        "!\trefs/heads/protected:\t[remote rejected] (protected branch)\n"
        "Done\n"
    )
    results = _parse_porcelain_delete("origin", stdout, ["feat-a", "protected"])
    by = {r.branch: r for r in results}
    assert by["origin/feat-a"].ok is True
    assert by["origin/protected"].ok is False
    assert "rejected" in by["origin/protected"].message


def test_missing_line_marks_failed():
    results = _parse_porcelain_delete("origin", "", ["gone"])
    assert results[0].branch == "origin/gone"
    assert results[0].ok is False
