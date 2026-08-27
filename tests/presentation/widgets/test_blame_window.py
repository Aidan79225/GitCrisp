"""Tests for the blame window."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from git_gui.domain.entities import BlameLine
from git_gui.presentation.theme import get_theme_manager
from git_gui.presentation.widgets.blame_window import (
    AUTHOR_CHARS,
    BlameWindow,
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


def _window(qtbot, lines=None, path="src/app.py", at_oid=None) -> tuple[BlameWindow, MagicMock]:
    queries = MagicMock()
    queries.get_blame.execute.return_value = list(LINES if lines is None else lines)
    w = BlameWindow(queries, path, at_oid)
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
    w = BlameWindow(queries, "logo.png")
    qtbot.addWidget(w)
    qtbot.waitUntil(lambda: "binary" in w._status.text())
    assert w._editor._lines == []


def test_a_result_for_a_revision_the_user_left_is_discarded(qtbot):
    """The user can walk back through revisions faster than blame returns."""
    w, _ = _window(qtbot)
    w._oid = "some-other-revision"

    w._on_loaded([_line(1, "stale", AAA, run_start=True)], "src/app.py", "")

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
    w._editor.set_lines(
        [_line(n, "x", AAA, run_start=n == 1) for n in range(1, 10001)], "src/app.py"
    )
    assert w._editor.gutter_width() > narrow


# ── Selecting a commit ───────────────────────────────────────────────────────


def test_opening_does_not_emit_before_the_user_picks_a_line(qtbot):
    """Opening blame must not yank the main window's commit selection."""
    queries = MagicMock()
    queries.get_blame.execute.return_value = list(LINES)
    w = BlameWindow(queries, "src/app.py")
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

    assert "no parent" in w._status.text()
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
    assert not w._back_btn.isEnabled()


def test_back_does_nothing_with_an_empty_history(qtbot):
    w, _ = _window(qtbot)
    w._go_back()
    assert w._oid is None


def test_author_column_is_capped(qtbot):
    """The gutter is a fixed width, so a long name must not push the columns apart."""
    assert len(_elide("An Extremely Long Contributor Name", AUTHOR_CHARS)) == AUTHOR_CHARS
