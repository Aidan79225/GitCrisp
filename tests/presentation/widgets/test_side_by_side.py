"""Aligning a unified hunk into two columns.

The whole difficulty is a change whose two sides are different lengths: three
lines removed against five added is one change, and if the shorter side is not
padded out the two panes drift apart for every row after it.
"""

from __future__ import annotations

import pytest

from git_gui.domain.entities import Hunk
from git_gui.presentation.widgets.side_by_side import align_hunk, parse_hunk_header


def _hunk(header: str, *lines: tuple[str, str]) -> Hunk:
    return Hunk(header=header, lines=[(o, c) for o, c in lines])


def _shape(rows) -> list[tuple[str | None, str | None]]:
    """Just the text of each side, which is what a reader compares."""
    return [(left.text if left else None, right.text if right else None) for left, right in rows]


# ── The header ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("@@ -12,7 +34,9 @@", (12, 34)),
        ("@@ -3 +7 @@", (3, 7)),  # a one-line side carries no count
        ("@@ -1,2 +1,2 @@ def f():", (1, 1)),  # trailing section heading
        ("not a header", (1, 1)),  # never stop the view drawing over this
    ],
)
def test_the_header_says_where_each_side_starts(header, expected):
    assert parse_hunk_header(header) == expected


# ── Context ──────────────────────────────────────────────────────────────────


def test_context_belongs_to_both_sides():
    rows = align_hunk(_hunk("@@ -10,2 +20,2 @@", (" ", "a\n"), (" ", "b\n")))

    assert _shape(rows) == [("a", "a"), ("b", "b")]
    assert [(left.number, right.number) for left, right in rows] == [(10, 20), (11, 21)]
    assert not any(cell.changed for row in rows for cell in row)


def test_an_unrecognised_origin_is_context():
    """git marks "\\ No newline at end of file" and the end-of-file variants
    with their own characters. The unified renderer counts them on both sides,
    and a row that only appeared on one of them would be a phantom change."""
    rows = align_hunk(_hunk("@@ -1,1 +1,1 @@", ("\\", " No newline at end of file\n")))

    left, right = rows[0]
    assert (left.number, right.number) == (1, 1)
    assert not left.changed and not right.changed


# ── Pairing a change ─────────────────────────────────────────────────────────


def test_equal_length_change_pairs_row_for_row():
    rows = align_hunk(
        _hunk(
            "@@ -1,2 +1,2 @@",
            ("-", "old one\n"),
            ("-", "old two\n"),
            ("+", "new one\n"),
            ("+", "new two\n"),
        )
    )

    assert _shape(rows) == [("old one", "new one"), ("old two", "new two")]
    assert all(cell.changed for row in rows for cell in row)


def test_more_additions_than_removals_pads_the_left():
    """Three removed against five added: five rows, the last two left blank."""
    rows = align_hunk(
        _hunk(
            "@@ -1,3 +1,5 @@",
            *[("-", f"old {i}\n") for i in range(3)],
            *[("+", f"new {i}\n") for i in range(5)],
        )
    )

    assert _shape(rows) == [
        ("old 0", "new 0"),
        ("old 1", "new 1"),
        ("old 2", "new 2"),
        (None, "new 3"),
        (None, "new 4"),
    ]


def test_more_removals_than_additions_pads_the_right():
    rows = align_hunk(
        _hunk(
            "@@ -1,3 +1,1 @@",
            *[("-", f"old {i}\n") for i in range(3)],
            ("+", "new 0\n"),
        )
    )

    assert _shape(rows) == [("old 0", "new 0"), ("old 1", None), ("old 2", None)]


def test_a_pure_addition_leaves_the_left_empty_throughout():
    rows = align_hunk(_hunk("@@ -0,0 +1,2 @@", ("+", "a\n"), ("+", "b\n")))

    assert _shape(rows) == [(None, "a"), (None, "b")]


def test_a_pure_deletion_leaves_the_right_empty_throughout():
    rows = align_hunk(_hunk("@@ -1,2 +0,0 @@", ("-", "a\n"), ("-", "b\n")))

    assert _shape(rows) == [("a", None), ("b", None)]


def test_context_closes_a_run_so_nothing_pairs_across_it():
    """Otherwise a deletion above the context line would sit opposite an
    addition below it, which is two changes shown as one."""
    rows = align_hunk(
        _hunk(
            "@@ -1,3 +1,3 @@",
            ("-", "gone\n"),
            (" ", "kept\n"),
            ("+", "added\n"),
        )
    )

    assert _shape(rows) == [("gone", None), ("kept", "kept"), (None, "added")]


# ── Line numbers ─────────────────────────────────────────────────────────────


def test_each_side_counts_only_its_own_lines():
    """The padding rows are where this goes wrong: they hold no line, so they
    must not advance the side they are padding."""
    rows = align_hunk(
        _hunk(
            "@@ -10,4 +20,5 @@",
            (" ", "context\n"),
            ("-", "old\n"),
            ("+", "new a\n"),
            ("+", "new b\n"),
            (" ", "tail\n"),
        )
    )

    left = [cell.number if cell else None for cell, _ in rows]
    right = [cell.number if cell else None for _, cell in rows]
    assert left == [10, 11, None, 12]
    assert right == [20, 21, 22, 23]


def test_numbers_survive_several_changes_in_one_hunk():
    rows = align_hunk(
        _hunk(
            "@@ -1,6 +1,6 @@",
            (" ", "a\n"),
            ("-", "b\n"),
            ("+", "B\n"),
            (" ", "c\n"),
            ("-", "d\n"),
            ("-", "e\n"),
            ("+", "D\n"),
            (" ", "f\n"),
        )
    )

    assert [(cell.number if cell else None) for cell, _ in rows] == [1, 2, 3, 4, 5, 6]
    assert [(cell.number if cell else None) for _, cell in rows] == [1, 2, 3, 4, None, 5]


# ── Text ─────────────────────────────────────────────────────────────────────


def test_the_trailing_newline_is_dropped_but_nothing_else_is():
    rows = align_hunk(
        _hunk(
            "@@ -1,2 +1,2 @@",
            ("-", "  indented  \n"),
            ("+", "no newline at all"),
        )
    )

    assert _shape(rows) == [("  indented  ", "no newline at all")]


def test_an_empty_hunk_has_no_rows():
    assert align_hunk(_hunk("@@ -0,0 +0,0 @@")) == []
