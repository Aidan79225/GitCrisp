"""Tests for the reflog pane."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QFont, QFontMetrics

from git_gui.domain.entities import ReflogEntry
from git_gui.presentation.theme import get_theme_manager
from git_gui.presentation.widgets.reflog_pane import (
    _OPERATION_ROLES,
    ORPHAN_STRIPE_W,
    ROW_PAD,
    ReflogModel,
    ReflogPane,
    _operation_color,
)


def _entry(
    index: int,
    operation: str,
    summary: str,
    *,
    oid_old: str | None = "b" * 40,
    orphaned: bool = False,
    went_nowhere: bool = False,
):
    if went_nowhere:
        oid_old = f"{index:040d}"  # the ref ended up where it started
    return ReflogEntry(
        index=index,
        oid_new=f"{index:040d}",
        oid_old=oid_old,
        operation=operation,
        summary=summary,
        committer="Alice",
        timestamp=datetime(2026, 1, 1, 12, 0),
        is_orphaned=orphaned,
    )


ENTRIES = [
    _entry(0, "reset", "moving to HEAD"),
    _entry(1, "commit", "add a thing"),
    _entry(2, "commit", "add another thing"),
    _entry(3, "branch", "Created from HEAD", oid_old=None),  # the ref-creation entry
]


def _pane(
    qtbot, entries=None, *, expect_rows: int | None = None, branch: str | None = "master"
) -> tuple[ReflogPane, MagicMock]:
    queries = MagicMock()
    supplied = list(ENTRIES if entries is None else entries)
    queries.get_reflog.execute.return_value = supplied
    queries.get_repo_state.execute.return_value.head_branch = branch
    pane = ReflogPane(queries)
    qtbot.addWidget(pane)
    wanted = len(supplied) if expect_rows is None else expect_rows
    qtbot.waitUntil(lambda: pane._model.rowCount() == wanted)
    return pane, queries


# ── Colour coding ────────────────────────────────────────────────────────────


def test_operation_colour_ignores_the_qualifier(qtbot):
    """ "commit (amend)" is still a commit."""
    assert _operation_color("commit (amend)") == _operation_color("commit")
    assert _operation_color("rebase (finish)") == _operation_color("rebase")


def test_unknown_operations_fall_back_rather_than_crash(qtbot):
    colors = get_theme_manager().current.colors
    assert _operation_color("gc").name() == colors.status_unknown.lower()
    assert _operation_color("").name() == colors.status_unknown.lower()


def test_every_operation_role_keeps_its_hue_across_themes(qtbot):
    """A colour meaning "moved the branch" has to mean that in either theme.

    status_modified is amber in light and blue in dark, which would have put
    checkout next to reset on the light theme — the opposite of the point.
    """
    manager = get_theme_manager()
    original = manager.mode
    try:
        seen: dict[str, list[str]] = {}
        for mode in ("light", "dark"):
            manager.set_mode(mode)
            colors = manager.current.colors
            for role in set(_OPERATION_ROLES.values()) | {"status_unknown"}:
                seen.setdefault(role, []).append(getattr(colors, role))

        for role, (light, dark) in seen.items():
            assert _hue(light) == pytest.approx(_hue(dark), abs=30), (
                f"{role} changes hue between themes: {light} vs {dark}"
            )
    finally:
        manager.set_mode(original)


def _hue(hex_color: str) -> float:
    from PySide6.QtGui import QColor

    return QColor(hex_color).hue()


def test_destructive_and_navigational_operations_are_told_apart(qtbot):
    """reset must not look like checkout — finding resets is the scanning job."""
    manager = get_theme_manager()
    original = manager.mode
    try:
        for mode in ("light", "dark"):
            manager.set_mode(mode)
            assert _hue(_operation_color("reset").name()) != pytest.approx(
                _hue(_operation_color("checkout").name()), abs=40
            ), f"reset and checkout are too close on the {mode} theme"
    finally:
        manager.set_mode(original)


# ── Model ────────────────────────────────────────────────────────────────────


def test_model_reports_the_widest_operation_for_column_alignment(qtbot):
    """Chips differ in width; the summaries must still line up."""

    model = ReflogModel(list(ENTRIES))
    fm = QFontMetrics(QFont())
    assert model.widest_operation(fm) == max(fm.horizontalAdvance(e.operation) for e in ENTRIES)


def test_model_lookup_is_bounded(qtbot):
    model = ReflogModel(list(ENTRIES))
    assert model.entry_at(0).operation == "reset"
    assert model.entry_at(len(ENTRIES)) is None
    assert model.entry_at(-1) is None


def test_widest_operation_of_an_empty_model_is_zero(qtbot):

    assert ReflogModel([]).widest_operation(QFontMetrics(QFont())) == 0


# ── Loading ──────────────────────────────────────────────────────────────────


def test_loads_head_and_says_how_much_it_found(qtbot):
    pane, queries = _pane(qtbot)
    queries.get_reflog.execute.assert_called_once_with("HEAD")
    assert "4 movements" in pane._status.full_text()


def test_failure_is_surfaced_rather_than_swallowed(qtbot):
    queries = MagicMock()
    queries.get_reflog.execute.side_effect = ValueError("No such ref: refs/heads/nope")
    pane = ReflogPane(queries, "refs/heads/nope")
    qtbot.addWidget(pane)
    qtbot.waitUntil(lambda: "No such ref" in pane._status.full_text())
    assert pane._model.rowCount() == 0


# ── Selection ────────────────────────────────────────────────────────────────


def test_picking_a_row_hands_over_the_commit_it_moved_to(qtbot):
    pane, _ = _pane(qtbot)
    got: list[str] = []
    pane.commit_selected.connect(got.append)

    pane.select_row(1)

    assert got == [ENTRIES[1].oid_new]


def test_re_picking_the_same_commit_does_not_re_emit(qtbot):
    """Two entries can land on one commit; that is not a new selection."""
    same = "c" * 40
    entries = [_entry(0, "reset", "a"), _entry(1, "checkout", "b")]
    entries[0].oid_new = same
    entries[1].oid_new = same
    pane, _ = _pane(qtbot, entries)
    got: list[str] = []
    pane.commit_selected.connect(got.append)

    pane.select_row(0)
    pane.select_row(1)

    assert got == [same]


def test_current_entry_follows_the_selection(qtbot):
    pane, _ = _pane(qtbot)
    pane.select_row(2)
    assert pane.current_entry().summary == "add another thing"


# ── Restore ──────────────────────────────────────────────────────────────────


class _FakeMenu:
    """Stand-in for QMenu; PySide6 types reject attribute patching."""

    choose = True
    actions: ClassVar[list] = []

    def __init__(self, *_a, **_k) -> None:
        self._action = None

    def addAction(self, text: str):
        self._action = _FakeAction(text)
        _FakeMenu.actions.append(self._action)
        return self._action

    def exec(self, *_a, **_k):
        return self._action if _FakeMenu.choose else None


class _FakeAction:
    def __init__(self, text: str) -> None:
        self.text = text
        self.enabled = True
        self.tooltip = ""

    def setEnabled(self, value: bool) -> None:
        self.enabled = value

    def setToolTip(self, value: str) -> None:
        self.tooltip = value


def _menu_on(pane, row, monkeypatch, *, choose=True):
    import git_gui.presentation.widgets.reflog_pane as module

    _FakeMenu.choose = choose
    _FakeMenu.actions = []
    monkeypatch.setattr(module, "QMenu", _FakeMenu)
    monkeypatch.setattr(pane._view, "indexAt", lambda _pos: pane._model.index(row, 0))
    pane._show_menu(QPoint(10, 10))  # mapToGlobal needs a real point
    return _FakeMenu.actions


def test_restore_asks_for_the_state_before_the_entry(qtbot, monkeypatch):
    """Restoring means going back to where the ref was, not where it went."""
    pane, _ = _pane(qtbot)
    got: list[tuple] = []
    pane.restore_requested.connect(lambda oid, label: got.append((oid, label)))

    _menu_on(pane, 0, monkeypatch)

    assert got and got[0][0] == ENTRIES[0].oid_old
    assert "reset" in got[0][1], "the prompt needs to name what is being undone"


def test_restore_is_disabled_on_the_entry_that_created_the_ref(qtbot, monkeypatch):
    """There is no earlier state, so the action must not be offered."""
    pane, _ = _pane(qtbot)
    got: list[tuple] = []
    pane.restore_requested.connect(lambda oid, label: got.append((oid, label)))

    actions = _menu_on(pane, 3, monkeypatch)  # oid_old is None

    assert actions and actions[0].enabled is False
    assert got == []


def test_dismissing_the_menu_restores_nothing(qtbot, monkeypatch):
    pane, _ = _pane(qtbot)
    got: list[tuple] = []
    pane.restore_requested.connect(lambda oid, label: got.append((oid, label)))

    _menu_on(pane, 0, monkeypatch, choose=False)

    assert got == []


# ── Orphan marking ───────────────────────────────────────────────────────────


def test_the_tooltip_explains_what_an_orphan_is(qtbot):
    """A stripe cannot say "gc will take this"; the tooltip has to."""
    entries = [_entry(0, "commit", "lost", orphaned=True)]
    pane, _ = _pane(qtbot, entries)

    tip = pane._model.data(pane._model.index(0, 0), Qt.ToolTipRole)

    assert "only way back" in tip
    assert "expires" in tip


def test_a_reachable_entry_gets_the_plain_tooltip(qtbot):
    pane, _ = _pane(qtbot, [_entry(0, "commit", "fine")])

    tip = pane._model.data(pane._model.index(0, 0), Qt.ToolTipRole)

    assert "only way back" not in tip
    assert "Alice" in tip


def test_content_starts_at_the_same_x_marked_or_not(qtbot):
    """The orphan stripe's width is reserved on every row.

    Adding it only to the marked rows shifted their text right, undoing the
    column alignment the chip column exists to provide. This is a geometry
    fact, so it is checked as one — comparing rendered pixels ends up
    measuring the tint's effect on antialiasing instead.
    """
    from git_gui.presentation.widgets.reflog_pane import ReflogDelegate

    rect = QRect(0, 0, 600, 30)
    assert ReflogDelegate.content_left(rect) == rect.left() + ROW_PAD + ORPHAN_STRIPE_W


def test_the_stripe_never_overlaps_the_content(qtbot):
    from git_gui.presentation.widgets.reflog_pane import ReflogDelegate

    rect = QRect(0, 0, 600, 30)
    assert ReflogDelegate.content_left(rect) >= rect.left() + ORPHAN_STRIPE_W


# ── Folding the entries that changed nothing ─────────────────────────────────


def test_an_entry_that_ended_where_it_started_went_nowhere():
    from git_gui.presentation.widgets.reflog_pane import _went_nowhere

    assert _went_nowhere(_entry(0, "checkout", "same place", went_nowhere=True))
    assert not _went_nowhere(_entry(1, "commit", "moved"))


def test_the_ref_creation_entry_did_not_go_nowhere():
    """Its oid_old is absent, not equal — a different thing from a no-op."""
    from git_gui.presentation.widgets.reflog_pane import _went_nowhere

    assert not _went_nowhere(_entry(0, "branch", "Created from HEAD", oid_old=None))


def test_entries_that_changed_nothing_are_hidden_by_default(qtbot):
    """Restoring to one would put the ref where it already is."""
    entries = [
        _entry(0, "checkout", "same place", went_nowhere=True),
        _entry(1, "commit", "real work"),
        _entry(2, "checkout", "same place again", went_nowhere=True),
    ]
    pane, _ = _pane(qtbot, entries, expect_rows=1)

    assert pane._model.rowCount() == 1
    assert pane._model.entry_at(0).summary == "real work"
    assert pane._model.hidden_count() == 2


def test_a_checkout_that_moved_head_is_kept(qtbot):
    """Filtering by operation type would have thrown these away."""
    entries = [_entry(0, "checkout", "switched to another commit")]
    pane, _ = _pane(qtbot, entries, expect_rows=1)

    assert pane._model.rowCount() == 1


def test_an_orphan_is_never_hidden(qtbot):
    """Reaching those is the one thing nothing else in the app can do."""
    entries = [
        _entry(
            0, "checkout", "went nowhere but is all that holds it", went_nowhere=True, orphaned=True
        )
    ]
    pane, _ = _pane(qtbot, entries, expect_rows=1)

    assert pane._model.rowCount() == 1
    assert pane._model.hidden_count() == 0


def test_show_every_movement_brings_them_back(qtbot):
    entries = [
        _entry(0, "checkout", "same place", went_nowhere=True),
        _entry(1, "commit", "real work"),
    ]
    pane, _ = _pane(qtbot, entries, expect_rows=1)

    pane._show_all_box.setChecked(True)

    assert pane._model.rowCount() == 2
    assert pane._model.hidden_count() == 0


def test_the_status_line_says_how_many_are_hidden(qtbot):
    entries = [
        _entry(0, "checkout", "same place", went_nowhere=True),
        _entry(1, "commit", "real work"),
    ]
    pane, _ = _pane(qtbot, entries, expect_rows=1)

    assert "1 that changed nothing hidden" in pane._status.full_text()

    pane._show_all_box.setChecked(True)
    assert "hidden" not in pane._status.full_text()


def test_filtering_does_not_renumber_the_entries(qtbot):
    """The position is HEAD@{n}, which git counts over every entry.

    Renumbering to the visible rows would make the label a lie and the sha it
    names unreachable from the command line.
    """
    entries = [
        _entry(0, "checkout", "same place", went_nowhere=True),
        _entry(1, "commit", "real work"),
        _entry(2, "checkout", "same place", went_nowhere=True),
        _entry(3, "commit", "more work"),
    ]
    pane, _ = _pane(qtbot, entries, expect_rows=2)

    assert [pane._model.entry_at(r).index for r in range(2)] == [1, 3]


# ── What the restore action names ────────────────────────────────────────────


def test_the_restore_action_names_the_branch_it_moves(qtbot, monkeypatch):
    """Restoring is a reset, and a reset moves the current branch.

    The action said "Restore HEAD", which left the one ref that actually
    changes unnamed — and HEAD's reflog spans checkouts, so the entry picked
    may well be from a time the user was on a different branch.
    """
    pane, _ = _pane(qtbot, branch="feature/x")

    actions = _menu_on(pane, 0, monkeypatch, choose=False)

    assert actions[0].text == "Restore feature/x to the state before this"


def test_a_detached_head_names_head_because_head_is_what_moves(qtbot, monkeypatch):
    """With no branch checked out, the old wording was the right one."""
    pane, _ = _pane(qtbot, branch=None)

    actions = _menu_on(pane, 0, monkeypatch, choose=False)

    assert actions[0].text == "Restore HEAD to the state before this"


def test_a_failed_load_does_not_leave_a_stale_branch_on_the_action(qtbot, monkeypatch):
    queries = MagicMock()
    queries.get_reflog.execute.side_effect = ValueError("No such ref: refs/heads/nope")
    pane = ReflogPane(queries, "refs/heads/nope")
    qtbot.addWidget(pane)
    qtbot.waitUntil(lambda: "No such ref" in pane._status.full_text())

    assert pane.restore_target() == "refs/heads/nope"


# ── Header layout ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("width", [320, 400, 520, 700, 900])
def test_the_header_controls_stay_reachable_however_narrow_the_pane(qtbot, width):
    """The status line gives way; the checkbox and the close button do not.

    A plain QLabel treats its full text as a minimum width, so below the
    header's natural width the layout pushed the close button off the right
    edge and into the checkbox instead of shortening the status line.
    """
    pane, _ = _pane(qtbot)
    pane.show()
    pane.resize(width, 400)
    qtbot.waitUntil(lambda: pane._close_btn.geometry().right() > 0)

    status, box, close = pane._status, pane._show_all_box, pane._close_btn
    assert close.geometry().right() <= width, "the close button ran off the pane"
    assert status.geometry().right() <= box.geometry().left(), "the status line ran into the box"
    assert box.geometry().right() <= close.geometry().left(), "the box ran into the close button"


def test_a_cut_status_line_keeps_the_whole_text_in_its_tooltip(qtbot):
    pane, _ = _pane(qtbot)
    pane.show()
    pane.resize(320, 400)

    assert pane._status.text() != pane._status.full_text(), "this width has to cut it"
    assert pane._status.text().endswith("…")
    assert pane._status.toolTip() == pane._status.full_text()
