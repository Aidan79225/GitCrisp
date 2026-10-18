"""The domain's one list of libgit2's "no newline at end of file" markers."""

from __future__ import annotations

from git_gui.domain.entities import NO_NEWLINE_MARKERS, LineKind


def test_the_markers_are_the_three_eofnl_kinds_and_no_line_of_a_file():
    assert NO_NEWLINE_MARKERS == {
        LineKind.ADDED_EOFNL,
        LineKind.REMOVED_EOFNL,
        LineKind.CONTEXT_EOFNL,
    }
    assert not {LineKind.ADDED, LineKind.REMOVED, LineKind.CONTEXT} & NO_NEWLINE_MARKERS


def test_a_raw_libgit2_origin_is_recognised_as_a_marker():
    """Infrastructure checks pygit2's origin characters, not LineKind members."""
    assert all(origin in NO_NEWLINE_MARKERS for origin in (">", "<", "="))
