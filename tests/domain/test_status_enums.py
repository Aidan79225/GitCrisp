"""The staging/delta vocabulary, as enums rather than bare strings.

Every member's value is the string the codebase used before, and every enum is
a StrEnum, so a member compares and hashes equal to that string. That is what
lets the layers migrate one at a time: infrastructure can hand out
``StagingState.STAGED`` while a widget still asks ``status == "staged"``, and
neither has to know about the other yet.
"""

from __future__ import annotations

from enum import StrEnum

from git_gui.domain.entities import FileDelta, Hunk, LineKind, StagingState


def test_every_status_vocabulary_is_a_str_enum():
    for enum in (StagingState, FileDelta, LineKind):
        assert issubclass(enum, StrEnum)


def test_staging_states_keep_their_previous_strings():
    assert list(StagingState) == ["staged", "unstaged", "untracked", "conflicted"]


def test_file_deltas_keep_their_previous_strings():
    assert list(FileDelta) == ["added", "modified", "deleted", "renamed", "unknown"]


def test_line_kinds_are_the_diff_prefixes():
    assert (LineKind.ADDED, LineKind.REMOVED, LineKind.CONTEXT) == ("+", "-", " ")


def test_a_member_is_interchangeable_with_its_string():
    """Untouched call sites keep working while the layers migrate."""
    assert StagingState.STAGED == "staged"
    assert {"staged": 1}[StagingState.STAGED] == 1
    assert {StagingState.STAGED: 1}["staged"] == 1


def test_a_string_round_trips_into_its_member():
    assert StagingState("conflicted") is StagingState.CONFLICTED
    assert FileDelta("renamed") is FileDelta.RENAMED
    assert LineKind("+") is LineKind.ADDED


def test_the_no_newline_markers_keep_their_own_characters():
    """libgit2 marks a missing trailing newline with its own origin chars."""
    assert LineKind("=") is LineKind.CONTEXT_EOFNL
    assert LineKind(">") is LineKind.ADDED_EOFNL
    assert LineKind("<") is LineKind.REMOVED_EOFNL


def test_an_unknown_origin_reads_as_context_rather_than_raising():
    """A diff must still render when libgit2 hands back an origin we don't know."""
    assert LineKind("B") is LineKind.CONTEXT


def test_a_hunk_line_carries_its_kind():
    hunk = Hunk(header="@@ -1 +1 @@", lines=[(LineKind.REMOVED, "old"), (LineKind.ADDED, "new")])

    assert [kind for kind, _ in hunk.lines] == ["-", "+"]
