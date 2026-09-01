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
):
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


def _pane(qtbot, entries=None) -> tuple[ReflogPane, MagicMock]:
    queries = MagicMock()
    queries.get_reflog.execute.return_value = list(ENTRIES if entries is None else entries)
    pane = ReflogPane(queries)
    qtbot.addWidget(pane)
    qtbot.waitUntil(lambda: pane._model.rowCount() == len(queries.get_reflog.execute.return_value))
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
    assert "4 movements" in pane._status.text()


def test_failure_is_surfaced_rather_than_swallowed(qtbot):
    queries = MagicMock()
    queries.get_reflog.execute.side_effect = ValueError("No such ref: refs/heads/nope")
    pane = ReflogPane(queries, "refs/heads/nope")
    qtbot.addWidget(pane)
    qtbot.waitUntil(lambda: "No such ref" in pane._status.text())
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
