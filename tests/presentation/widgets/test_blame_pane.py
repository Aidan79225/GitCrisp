"""Tests for the blame window."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from git_gui.domain.entities import BlameLine
from git_gui.presentation.theme import get_theme_manager
from git_gui.presentation.widgets.blame_pane import (
    AUTHOR_CHARS,
    COL_GAP,
    GUTTER_PAD,
    SHA_CHARS,
    STRIPE_W,
    BlamePane,
    _elide,
    _lane_color,
)


def _line(no: int, text: str, oid: str, *, run_start: bool) -> BlameLine:
    return BlameLine(
        line_no=no,
        text=text,
        commit_oid=oid,
        author="Alice",
        timestamp=datetime(2026, 1, 1),
        summary="did a thing",
        is_run_start=run_start,
    )


AAA = "a" * 40
BBB = "b" * 40

# Two lines from one commit, then one from another — enough to tell "emit per
# run" apart from "emit per line".
LINES = [
    _line(1, "first", AAA, run_start=True),
    _line(2, "second", AAA, run_start=False),
    _line(3, "third", BBB, run_start=True),
]


def _window(qtbot, lines=None, path="src/app.py", at_oid=None) -> tuple[BlamePane, MagicMock]:
    queries = MagicMock()
    queries.get_blame.execute.return_value = list(LINES if lines is None else lines)
    w = BlamePane(queries, path, at_oid)
    qtbot.addWidget(w)
    qtbot.waitUntil(lambda: len(w._editor._lines) == len(queries.get_blame.execute.return_value))
    return w, queries


# ── Helpers ──────────────────────────────────────────────────────────────────


def test_lane_color_is_stable_per_commit_and_from_the_graph_palette(qtbot):
    palette = get_theme_manager().current.colors.graph_lane_colors
    assert _lane_color(AAA) == _lane_color(AAA)
    assert _lane_color(AAA).name() in [c.lower() for c in palette]


def test_elide_leaves_short_text_alone_and_truncates_long_text():
    assert _elide("Alice", 10) == "Alice"
    long = _elide("A Very Long Contributor Name", 10)
    assert len(long) == 10 and long.endswith("…")


# ── Loading ──────────────────────────────────────────────────────────────────


def test_loads_the_file_and_shows_the_revision_in_the_title(qtbot):
    w, queries = _window(qtbot)
    queries.get_blame.execute.assert_called_once_with("src/app.py", at_oid=None)
    assert w._editor.toPlainText() == "first\nsecond\nthird"
    assert "src/app.py" in w.windowTitle()
    assert "HEAD" in w.windowTitle()


def test_title_names_the_revision_when_blaming_an_older_commit(qtbot):
    w, _ = _window(qtbot, at_oid=AAA)
    assert AAA[:8] in w.windowTitle()


def test_failure_is_surfaced_rather_than_swallowed(qtbot):
    queries = MagicMock()
    queries.get_blame.execute.side_effect = ValueError("Cannot blame a binary file: logo.png")
    w = BlamePane(queries, "logo.png")
    qtbot.addWidget(w)
    qtbot.waitUntil(lambda: "binary" in w._status.full_text())
    assert w._editor._lines == []


def test_a_result_for_a_revision_the_user_left_is_discarded(qtbot):
    """The user can walk back through revisions faster than blame returns."""
    w, _ = _window(qtbot)
    w._oid = "some-other-revision"

    w._on_loaded([_line(1, "stale", AAA, run_start=True)], [], "src/app.py", "")

    assert w._editor.toPlainText() == "first\nsecond\nthird"


def test_theme_change_recolours_the_code(qtbot):
    """Syntax colours are baked into the document when the file loads.

    A repaint alone leaves the previous theme's palette in the char formats,
    and light-theme token colours on a dark surface are unreadable.
    """
    from PySide6.QtGui import QTextCursor

    manager = get_theme_manager()
    original = manager.mode
    try:
        manager.set_mode("light")
        w, _ = _window(qtbot, lines=[_line(1, '"hello"', AAA, run_start=True)])

        def string_color() -> str:
            cursor = QTextCursor(w._editor.document())
            cursor.setPosition(1)
            cursor.setPosition(2, QTextCursor.KeepAnchor)
            return cursor.charFormat().foreground().color().name().lower()

        light = string_color()
        assert light == manager.current.colors.syntax_string.lower()

        manager.set_mode("dark")
        dark = string_color()
        assert dark == manager.current.colors.syntax_string.lower()
        assert dark != light
    finally:
        manager.set_mode(original)


# ── Line lookup ──────────────────────────────────────────────────────────────


def test_line_lookup_is_bounded(qtbot):
    w, _ = _window(qtbot)
    assert w._editor.line_at_block(0).text == "first"
    assert w._editor.line_at_block(2).text == "third"
    assert w._editor.line_at_block(3) is None
    assert w._editor.line_at_block(-1) is None


def test_gutter_widens_with_the_line_number_column(qtbot):
    w, _ = _window(qtbot)
    narrow = w._editor.gutter_width()
    w._editor.set_lines([_line(n, "x", AAA, run_start=n == 1) for n in range(1, 10001)], [])
    assert w._editor.gutter_width() > narrow


def test_the_gutter_carries_the_author_and_nothing_else(qtbot):
    """Sha, author and date together cost ~190px of a ~263px gutter.

    In a pane that shares its width with the diff, that came straight out of
    the code — to repeat what picking the line or hovering it already gives.
    """
    from PySide6.QtGui import QFontMetrics

    w, _ = _window(qtbot)
    editor = w._editor
    fm = QFontMetrics(editor.font())

    author_and_line_number = (
        STRIPE_W
        + GUTTER_PAD
        + editor.author_column_width()
        + COL_GAP
        + fm.horizontalAdvance("99")
        + GUTTER_PAD
    )
    assert editor.gutter_width() == author_and_line_number
    assert editor.gutter_width() < fm.horizontalAdvance("0" * SHA_CHARS) + author_and_line_number


def test_the_sha_and_date_are_still_reachable_on_the_line(qtbot):
    """Dropping the columns is only fair because the tooltip carries them."""
    w, _ = _window(qtbot)
    w.show()
    # The document's top margin means y=0 is above the first block; find the
    # first y that lands on one rather than assuming where it starts.
    editor = w._editor
    qtbot.waitUntil(lambda: any(editor.block_at_y(y) is not None for y in range(40)))
    y = next(y for y in range(40) if editor.block_at_y(y) is not None)

    tip = editor.attribution_at(y)

    assert "2026-01-01" in tip
    assert AAA[:SHA_CHARS] in tip
    assert "did a thing" in tip, "and the subject, which never had a column"


# ── Selecting a commit ───────────────────────────────────────────────────────


def test_opening_does_not_emit_before_the_user_picks_a_line(qtbot):
    """Opening blame must not yank the main window's commit selection."""
    queries = MagicMock()
    queries.get_blame.execute.return_value = list(LINES)
    w = BlamePane(queries, "src/app.py")
    qtbot.addWidget(w)
    got: list[str] = []
    w.commit_selected.connect(got.append)
    qtbot.waitUntil(lambda: len(w._editor._lines) == 3)

    assert got == []


def test_selecting_a_line_emits_its_commit(qtbot):
    w, _ = _window(qtbot)
    got: list[str] = []
    w.commit_selected.connect(got.append)

    w._editor.select_line_at_block(2)
    w._editor.select_line_at_block(0)

    assert got == [BBB, AAA]


def test_moving_within_a_run_does_not_re_emit(qtbot):
    """Emitting per line would re-drive the main window on every arrow key."""
    w, _ = _window(qtbot)
    got: list[str] = []
    w.commit_selected.connect(got.append)

    w._editor.select_line_at_block(2)
    w._editor.select_line_at_block(0)
    w._editor.select_line_at_block(1)  # same commit as line 1

    assert got == [BBB, AAA]


# ── Blame before ─────────────────────────────────────────────────────────────


def test_blame_before_reblames_at_the_parent_and_enables_back(qtbot):
    w, queries = _window(qtbot)
    queries.get_commit_detail.execute.return_value = MagicMock(parents=["parent-oid"])

    w._blame_before(BBB)
    qtbot.waitUntil(lambda: w._oid == "parent-oid")

    assert w._back_btn.isEnabled()
    queries.get_blame.execute.assert_called_with("src/app.py", at_oid="parent-oid")


def test_blame_before_a_parentless_commit_reports_and_stays_put(qtbot):
    """A root commit — or a graft boundary in a shallow clone — has nothing before it."""
    w, queries = _window(qtbot)
    queries.get_commit_detail.execute.return_value = MagicMock(parents=[])

    w._blame_before(BBB)

    assert "no parent" in w._status.full_text()
    assert w._history == []
    assert w._oid is None


def test_back_returns_to_the_previous_revision(qtbot):
    w, queries = _window(qtbot)
    queries.get_commit_detail.execute.return_value = MagicMock(parents=["parent-oid"])
    w._blame_before(BBB)
    qtbot.waitUntil(lambda: w._oid == "parent-oid")

    w._go_back()
    qtbot.waitUntil(lambda: w._oid is None)

    assert w._history == []
    assert w._back_btn.isHidden(), "nothing left to climb out of"


def test_back_is_absent_until_there_is_a_dig_to_climb_out_of(qtbot):
    """It read as "back to the commit list" sitting greyed out beside the ✕.

    It undoes one step of "Blame before this commit" and nothing else, so it
    is only there once such a step has been taken.
    """
    w, queries = _window(qtbot)
    assert w._back_btn.isHidden()

    queries.get_commit_detail.execute.return_value = MagicMock(parents=["parent-oid"])
    w._blame_before(BBB)
    qtbot.waitUntil(lambda: w._oid == "parent-oid")

    assert not w._back_btn.isHidden()


def test_back_does_nothing_with_an_empty_history(qtbot):
    w, _ = _window(qtbot)
    w._go_back()
    assert w._oid is None


def test_a_long_author_widens_the_gutter_no_further_than_the_cap(qtbot):
    """The gutter grows with the widest author shown, up to AUTHOR_CHARS of them."""
    at_cap, _ = _window(qtbot, lines=[replace(LINES[0], author="W" * AUTHOR_CHARS)])
    past_cap, _ = _window(qtbot, lines=[replace(LINES[0], author="W" * (AUTHOR_CHARS * 3))])

    assert past_cap._editor.gutter_width() <= at_cap._editor.gutter_width()


# ── Picking a line of the first run ──────────────────────────────────────────


def test_picking_a_line_of_the_first_run_loads_its_commit(qtbot):
    """Opening blame emits nothing, so nothing of line 1's commit is showing yet.

    The diff pane still holds the revision blame was opened from; treating line
    1's commit as already emitted dropped the user's first pick of it.
    """
    w, _ = _window(qtbot, at_oid="x" * 40)
    got: list[str] = []
    w.commit_selected.connect(got.append)

    w._editor.select_line_at_block(1)

    assert got == [AAA]


def test_a_gutter_click_on_the_line_the_cursor_is_already_on_loads_its_commit(qtbot):
    """Loading leaves the cursor on line 1, so clicking it moves nothing."""
    w, _ = _window(qtbot)
    got: list[str] = []
    w.commit_selected.connect(got.append)

    w._editor.select_line_at_block(0)

    assert got == [AAA]


# ── Syntax pass cost ─────────────────────────────────────────────────────────


def test_the_file_is_tokenized_off_the_gui_thread(qtbot, monkeypatch):
    """Tokenizing a few thousand lines takes long enough to freeze the window.

    It happens once, in the load worker; a theme change only re-colours.
    """
    import threading

    from git_gui.presentation.widgets import blame_pane

    tokenizing_threads: list[threading.Thread] = []
    real_tokenize = blame_pane.tokenize

    def spy(text: str, path: str):
        tokenizing_threads.append(threading.current_thread())
        return real_tokenize(text, path)

    monkeypatch.setattr(blame_pane, "tokenize", spy)
    w, _ = _window(qtbot)
    w._editor.restyle()

    assert tokenizing_threads, "the file is still tokenized, just not here"
    assert threading.main_thread() not in tokenizing_threads


def test_a_theme_change_recolours_in_a_single_document_change(qtbot):
    """One change per token re-laid out the document once per token."""
    lines = [_line(n, f"value_{n} = {n}  # note", AAA, run_start=n == 1) for n in range(1, 51)]
    w, _ = _window(qtbot, lines=lines)
    changes: list[tuple[int, int, int]] = []
    w._editor.document().contentsChange.connect(lambda *change: changes.append(change))

    w._editor.restyle()

    assert len(changes) <= 1


# ── Syntax colours past an astral character ──────────────────────────────────


def test_an_emoji_does_not_shift_the_colours_after_it(qtbot):
    """A document counts an emoji as two positions; a Python string as one."""
    from PySide6.QtGui import QTextCursor

    lines = [
        _line(1, 'x = "\U0001f389"', AAA, run_start=True),
        _line(2, "def foo():", AAA, run_start=False),
    ]
    w, _ = _window(qtbot, lines=lines, path="x.py")
    keyword = get_theme_manager().current.colors.syntax_keyword.lower()

    def colour_at(position: int) -> str:
        cursor = QTextCursor(w._editor.document())
        cursor.setPosition(position)
        cursor.setPosition(position + 1, QTextCursor.KeepAnchor)
        return cursor.charFormat().foreground().color().name().lower()

    def_start = w._editor.document().findBlockByNumber(1).position()
    assert [colour_at(def_start + i) for i in range(3)] == [keyword] * 3
    assert colour_at(def_start + 3) != keyword, "the space after def stays plain"


# ── Gutter after a font change ───────────────────────────────────────────────


def test_the_gutter_widens_with_a_larger_font_after_a_theme_change(qtbot):
    """The typography scale reaches the editor as a new font, then a theme change.

    Measured once at load, the gutter kept its old width: author names ran
    into the line numbers and the numbers were clipped.
    """
    w, _ = _window(qtbot)
    editor = w._editor
    before = editor.gutter_width()
    font = editor.font()
    font.setPointSizeF(font.pointSizeF() * 1.6)
    editor.setFont(font)

    editor.restyle()

    assert editor.gutter_width() == editor._measure_gutter() > before
    assert editor._gutter.width() == editor.gutter_width()


# ── Header width ─────────────────────────────────────────────────────────────


LONG_PATH = "git_gui/presentation/main_window/" + "deeply_nested_module/" * 3 + "flows.py"


def test_a_long_path_does_not_widen_the_pane(qtbot):
    """A plain label's full text is its minimum width, and so the pane's.

    The splitter could not narrow the blame column below the path's length,
    and took the space from the diff pane instead.
    """
    short, _ = _window(qtbot, path="a.py")
    long, _ = _window(qtbot, path=LONG_PATH)

    assert long.minimumSizeHint().width() == short.minimumSizeHint().width()


def test_a_cut_path_stays_whole_in_the_tooltip(qtbot):
    w, _ = _window(qtbot, path=LONG_PATH)
    w.show()
    narrowest = w.minimumSizeHint().width()
    w.resize(narrowest, 400)
    qtbot.waitUntil(lambda: w.width() == narrowest)

    assert w._status.text() != w._status.full_text(), "this width has to cut it"
    assert LONG_PATH in w._status.toolTip()


# ── Characters a document breaks on and git does not ─────────────────────────


@pytest.mark.parametrize("inside", ["\r", " "], ids=["carriage return", "paragraph sep"])
def test_a_line_git_keeps_whole_stays_one_line_beside_its_gutter(qtbot, inside):
    """The gutter pairs the nth text block with the nth blamed line.

    A document starts a block at a lone carriage return and at U+2029, where
    git does not end the line, so every gutter entry below one named the line
    above its own.
    """
    lines = [
        _line(1, f"a{inside}b", AAA, run_start=True),
        _line(2, "c", BBB, run_start=True),
    ]
    w, _ = _window(qtbot, lines=lines)
    document = w._editor.document()

    assert document.blockCount() == len(lines)
    assert document.findBlockByNumber(1).text() == "c"
