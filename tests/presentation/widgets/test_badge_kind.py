"""The badge letter and colour both key off one value.

The working-tree list and the file navigator each carried their own copy of the
delta→letter table, and they had already drifted: only one of them knew about
conflicts. One table now, and `badge_kind` decides what a row's badge stands
for.
"""

from __future__ import annotations

from git_gui.domain.entities import FileDelta, FileStatus, StagingState
from git_gui.presentation.widgets.file_list_view import (
    BADGE_LABEL,
    UNKNOWN_LABEL,
    badge_kind,
)


def _file(status: StagingState, delta: FileDelta) -> FileStatus:
    return FileStatus(path="a.txt", status=status, delta=delta)


def test_an_ordinary_row_is_badged_by_its_delta():
    assert badge_kind(_file(StagingState.UNSTAGED, FileDelta.MODIFIED)) is FileDelta.MODIFIED
    assert badge_kind(_file(StagingState.STAGED, FileDelta.ADDED)) is FileDelta.ADDED


def test_a_conflict_outranks_the_delta():
    """It is the thing the user has to act on, whatever the delta says."""
    conflicted = _file(StagingState.CONFLICTED, FileDelta.MODIFIED)

    assert badge_kind(conflicted) is StagingState.CONFLICTED
    assert BADGE_LABEL[badge_kind(conflicted)] == "C"


def test_a_row_with_no_file_falls_back_to_unknown():
    assert badge_kind(None) is FileDelta.UNKNOWN


def test_every_delta_has_a_letter():
    for delta in FileDelta:
        assert BADGE_LABEL[delta]


def test_a_value_from_outside_the_vocabulary_still_paints():
    """paint() runs for every row; a KeyError there takes the view down."""
    assert BADGE_LABEL.get("something-else", UNKNOWN_LABEL) == UNKNOWN_LABEL


def test_a_status_built_from_plain_strings_still_badges():
    """Enum members compare equal to their strings, so old callers keep working."""
    assert badge_kind(FileStatus(path="a", status="conflicted", delta="modified")) == "conflicted"
    assert badge_kind(FileStatus(path="a", status="unstaged", delta="deleted")) == "deleted"
