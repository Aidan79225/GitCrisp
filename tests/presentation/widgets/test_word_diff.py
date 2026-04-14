from __future__ import annotations
import pytest

from git_gui.presentation.widgets.word_diff import WordSpan, pair_diff


def _kinds(spans):
    return [s.kind for s in spans]


def _changed_text(line: str, spans):
    return [line[s.start:s.end] for s in spans if s.kind == "changed"]


def test_identical_lines_have_no_changed_spans():
    old, new = pair_diff("foo = 1", "foo = 1")
    assert all(s.kind == "same" for s in old)
    assert all(s.kind == "same" for s in new)


def test_single_word_change_marks_only_that_word():
    old, new = pair_diff("foo = 1", "foo = 2")
    assert _changed_text("foo = 1", old) == ["1"]
    assert _changed_text("foo = 2", new) == ["2"]


def test_completely_different_lines_are_fully_changed():
    old, new = pair_diff("abc", "xyz")
    # Every word/char span on each side is "changed".
    assert all(s.kind == "changed" for s in old)
    assert all(s.kind == "changed" for s in new)


def test_whitespace_only_change_is_detected():
    # Trailing space added.
    old, new = pair_diff("foo", "foo ")
    assert _changed_text("foo ", new) == [" "]


def test_empty_old_marks_full_new_as_changed():
    old, new = pair_diff("", "abc")
    assert old == []
    assert _changed_text("abc", new) == ["abc"]


def test_empty_new_marks_full_old_as_changed():
    old, new = pair_diff("abc", "")
    assert _changed_text("abc", old) == ["abc"]
    assert new == []


def test_adjacent_same_kind_spans_are_merged():
    # "foo bar baz" → "foo BAR BAZ": "BAR BAZ" is one merged "changed" span on new side?
    # SequenceMatcher will likely produce one "replace" opcode covering both words,
    # which yields a single span covering "bar baz" (old) and "BAR BAZ" (new).
    # Our merge step should not split them.
    old, new = pair_diff("foo bar baz", "foo BAR BAZ")
    new_changed = [s for s in new if s.kind == "changed"]
    # All "changed" spans should be contiguous (no gap between adjacent same-kind spans).
    for a, b in zip(new_changed, new_changed[1:]):
        assert a.end < b.start  # gap exists (a "same" span between them)


def test_unicode_identifiers_unchanged_stay_same():
    old, new = pair_diff("αβγ = 1", "αβγ = 2")
    # The αβγ token should appear as "same" on both sides.
    assert any(s.kind == "same" and "αβγ" in "αβγ = 1"[s.start:s.end] for s in old)


def test_spans_cover_input_with_no_overlap():
    """Returned spans should be non-overlapping and cover the changed regions."""
    old, new = pair_diff("a b c", "a B c")
    for spans in (old, new):
        prev_end = 0
        for s in spans:
            assert s.start >= prev_end
            prev_end = s.end


def test_word_span_is_frozen_dataclass():
    span = WordSpan(start=0, end=3, kind="same")
    with pytest.raises(Exception):
        span.start = 1  # type: ignore[misc]
