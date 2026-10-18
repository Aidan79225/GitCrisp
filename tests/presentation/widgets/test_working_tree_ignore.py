"""Tests for WorkingTreeWidget._ignore_file and set_repo_path.

Regression test for: after a repo switch, _ignore_file was writing to the
previous repo's .gitignore because WorkingTreeWidget._repo_path was not
being updated. set_repo_path now mirrors the sidebar's pattern, and
_on_repo_ready calls it alongside set_buses.
"""

from __future__ import annotations

import pygit2
import pytest

from git_gui.presentation.widgets.working_tree import WorkingTreeWidget
from tests.presentation.widgets.working_tree_helpers import working_tree_widget


def _make_minimal(qtbot, repo_path: str | None) -> WorkingTreeWidget:
    return working_tree_widget(qtbot, repo_path)


def test_ignore_file_creates_gitignore_when_missing(qtbot, tmp_path):
    """With no existing .gitignore, _ignore_file creates the file with
    a single trailing newline after the entry."""
    repo = tmp_path / "repo"
    repo.mkdir()

    w = _make_minimal(qtbot, str(repo))
    w._ignore_file("build/output")

    assert (repo / ".gitignore").read_text() == "/build/output\n"


def test_ignore_file_appends_with_separator_when_existing_has_no_trailing_newline(qtbot, tmp_path):
    """Pre-existing .gitignore without a trailing newline: the helper
    must insert a separator newline before the new entry."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".gitignore").write_text("*.log")  # no trailing newline

    w = _make_minimal(qtbot, str(repo))
    w._ignore_file("build/output")

    assert (repo / ".gitignore").read_text() == "*.log\n/build/output\n"


def test_ignore_file_skips_when_path_already_present(qtbot, tmp_path):
    """Duplicate entries are not appended."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".gitignore").write_text("/foo.py\n*.log\n")

    w = _make_minimal(qtbot, str(repo))
    w._ignore_file("foo.py")

    assert (repo / ".gitignore").read_text() == "/foo.py\n*.log\n"


def test_ignore_file_noop_when_repo_path_is_none(qtbot):
    """Empty-state guard: no repo active means the helper does nothing
    (no exception, no filesystem write)."""
    w = _make_minimal(qtbot, None)
    w._ignore_file("foo.py")  # must not raise


def test_set_repo_path_redirects_ignore_to_new_repo(qtbot, tmp_path):
    """Regression: after set_repo_path(new_path), _ignore_file writes to
    the new repo's .gitignore, NOT the one from construction. This was
    the silent failure mode when the user switched repos."""
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    repo_a.mkdir()
    repo_b.mkdir()

    w = _make_minimal(qtbot, str(repo_a))
    w.set_repo_path(str(repo_b))

    w._ignore_file("foo.py")

    assert (repo_b / ".gitignore").read_text() == "/foo.py\n"
    assert not (repo_a / ".gitignore").exists(), (
        "Add-to-.gitignore must follow the active repo after set_repo_path; "
        "writing to repo_a means _repo_path was stale."
    )


def test_set_repo_path_to_none_disables_ignore(qtbot, tmp_path):
    """After set_repo_path(None), _ignore_file becomes a no-op again."""
    repo = tmp_path / "repo"
    repo.mkdir()

    w = _make_minimal(qtbot, str(repo))
    w.set_repo_path(None)
    w._ignore_file("foo.py")

    assert not (repo / ".gitignore").exists()


# ── The line written matches exactly the file chosen ────────────────────────


def _ignored_after_choosing(qtbot, tmp_path, chosen: str, probe: str) -> bool:
    """Ignore *chosen* from the menu, then ask libgit2 whether *probe* is ignored."""
    repo = pygit2.init_repository(str(tmp_path))
    w = _make_minimal(qtbot, str(tmp_path))
    w._ignore_file(chosen)
    return repo.path_is_ignored(probe)


@pytest.mark.parametrize(
    "name",
    ["#notes.org#", "!keep.txt", "a[1].txt", "pages/[id].tsx", "star*.txt", "what?.txt"],
)
def test_a_name_with_gitignore_syntax_in_it_is_still_ignored(qtbot, tmp_path, name):
    """A leading '#' or '!' starts a comment or a negation; '[', '*', '?' are globs."""
    assert _ignored_after_choosing(qtbot, tmp_path, name, name)


def test_a_bracketed_name_does_not_ignore_a_file_it_never_named(qtbot, tmp_path):
    """Read as a glob, '[id]' matched pages/i.tsx instead."""
    assert not _ignored_after_choosing(qtbot, tmp_path, "pages/[id].tsx", "pages/i.tsx")


def test_a_root_file_does_not_ignore_its_namesakes_in_subfolders(qtbot, tmp_path):
    assert not _ignored_after_choosing(qtbot, tmp_path, "TODO.md", "docs/TODO.md")


def test_trailing_spaces_in_a_name_are_kept(qtbot, tmp_path):
    """Unescaped trailing spaces are dropped from a .gitignore line."""
    assert _ignored_after_choosing(qtbot, tmp_path, "notes  ", "notes  ")
    assert not _ignored_after_choosing(qtbot, tmp_path, "notes  ", "notes")


def test_a_second_click_on_an_escaped_name_adds_nothing(qtbot, tmp_path):
    w = _make_minimal(qtbot, str(tmp_path))
    w._ignore_file("a[1].txt")
    w._ignore_file("a[1].txt")
    assert (tmp_path / ".gitignore").read_text() == "/a\\[1].txt\n"
