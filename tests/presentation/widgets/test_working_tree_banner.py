"""Tests for the conflict banner in WorkingTreeWidget."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QWidget

from git_gui.presentation.widgets.working_tree import WorkingTreeWidget


def _make_widget(qtbot) -> WorkingTreeWidget:
    """Create a WorkingTreeWidget with minimal init bypass.

    Stubs `_queries` with a configured identity so `_on_commit`'s identity
    check passes; tests that exercise the missing-identity path override
    `get_identity.execute.return_value` themselves.
    """
    w = WorkingTreeWidget.__new__(WorkingTreeWidget)
    QWidget.__init__(w)
    from PySide6.QtWidgets import (
        QCheckBox,
        QHBoxLayout,
        QLabel,
        QPlainTextEdit,
        QPushButton,
    )

    w._conflict_banner = QWidget()
    banner_layout = QHBoxLayout(w._conflict_banner)
    w._banner_label = QLabel("")
    w._btn_abort = QPushButton("Abort")
    w._btn_commit = QPushButton("Commit")
    w._msg_edit = QPlainTextEdit()
    w._chk_amend = QCheckBox()
    w._draft_msg = ""
    banner_layout.addWidget(w._banner_label, 1)
    banner_layout.addWidget(w._btn_abort)
    w._conflict_banner.setVisible(False)
    w._btn_abort.clicked.connect(w._on_abort_clicked)
    w._queries = MagicMock()
    w._queries.get_identity.execute.return_value = ("Alice", "alice@example.com")
    w._commands = MagicMock()
    qtbot.addWidget(w)
    return w


def test_banner_hidden_when_clean(qtbot):
    w = _make_widget(qtbot)
    w.update_conflict_banner("CLEAN")
    assert w._conflict_banner.isVisible() is False
    assert w._btn_commit.text() == "Commit"


def test_banner_visible_during_merge(qtbot):
    w = _make_widget(qtbot)
    w.update_conflict_banner("MERGING")
    assert w._conflict_banner.isVisible() is True
    assert "Merge" in w._banner_label.text()
    assert w._btn_commit.text() == "Finish Merge"


def test_banner_visible_during_rebase(qtbot):
    w = _make_widget(qtbot)
    w.update_conflict_banner("REBASING")
    assert w._conflict_banner.isVisible() is True
    assert "Rebase" in w._banner_label.text()
    assert w._btn_commit.text() == "Continue Rebase"


def test_abort_emits_merge_abort(qtbot):
    w = _make_widget(qtbot)
    w.update_conflict_banner("MERGING")
    received = []
    w.merge_abort_requested.connect(lambda: received.append("merge_abort"))
    w._btn_abort.click()
    assert received == ["merge_abort"]


def test_abort_emits_rebase_abort(qtbot):
    w = _make_widget(qtbot)
    w.update_conflict_banner("REBASING")
    received = []
    w.rebase_abort_requested.connect(lambda: received.append("rebase_abort"))
    w._btn_abort.click()
    assert received == ["rebase_abort"]


def test_commit_button_emits_merge_continue(qtbot):
    w = _make_widget(qtbot)
    w.update_conflict_banner("MERGING")
    received = []
    w.merge_continue_requested.connect(lambda: received.append("merge_continue"))
    w._on_commit()
    assert received == ["merge_continue"]


def test_commit_button_emits_rebase_continue(qtbot):
    w = _make_widget(qtbot)
    w.update_conflict_banner("REBASING")
    received = []
    w.rebase_continue_requested.connect(lambda: received.append("rebase_continue"))
    w._on_commit()
    assert received == ["rebase_continue"]


def test_banner_visible_during_cherry_pick(qtbot):
    w = _make_widget(qtbot)
    w.update_conflict_banner("CHERRY_PICKING")
    assert w._conflict_banner.isVisible() is True
    assert "Cherry-pick" in w._banner_label.text()
    assert "Continue Cherry-pick" in w._btn_commit.text()


def test_banner_visible_during_revert(qtbot):
    w = _make_widget(qtbot)
    w.update_conflict_banner("REVERTING")
    assert w._conflict_banner.isVisible() is True
    assert "Revert" in w._banner_label.text()
    assert "Continue Revert" in w._btn_commit.text()


def test_abort_emits_cherry_pick_abort(qtbot):
    w = _make_widget(qtbot)
    w.update_conflict_banner("CHERRY_PICKING")
    received = []
    w.cherry_pick_abort_requested.connect(lambda: received.append("cp_abort"))
    w._btn_abort.click()
    assert received == ["cp_abort"]


def test_abort_emits_revert_abort(qtbot):
    w = _make_widget(qtbot)
    w.update_conflict_banner("REVERTING")
    received = []
    w.revert_abort_requested.connect(lambda: received.append("rv_abort"))
    w._btn_abort.click()
    assert received == ["rv_abort"]


def test_commit_emits_cherry_pick_continue(qtbot):
    w = _make_widget(qtbot)
    w.update_conflict_banner("CHERRY_PICKING")
    received = []
    w.cherry_pick_continue_requested.connect(lambda: received.append("cp_cont"))
    w._on_commit()
    assert received == ["cp_cont"]


def test_commit_emits_revert_continue(qtbot):
    w = _make_widget(qtbot)
    w.update_conflict_banner("REVERTING")
    received = []
    w.revert_continue_requested.connect(lambda: received.append("rv_cont"))
    w._on_commit()
    assert received == ["rv_cont"]


# --------------------------------------------------------------------
# Identity prompt during merge/rebase/cherry-pick/revert "continue".
# --------------------------------------------------------------------


@pytest.mark.parametrize(
    "state, signal_name",
    [
        ("MERGING", "merge_continue_requested"),
        ("REBASING", "rebase_continue_requested"),
        ("CHERRY_PICKING", "cherry_pick_continue_requested"),
        ("REVERTING", "revert_continue_requested"),
    ],
)
def test_continue_states_prompt_for_missing_identity(qtbot, monkeypatch, state, signal_name):
    """When identity is unset, _on_commit must open IdentityDialog before
    emitting the state-specific continue signal — for every state."""
    w = _make_widget(qtbot)
    w._queries.get_identity.execute.return_value = ("", "")
    w.update_conflict_banner(state)

    dialog_opened = []

    class _FakeDialog:
        def __init__(self, *_a, **_kw):
            dialog_opened.append(True)

        def exec(self):
            from PySide6.QtWidgets import QDialog

            return QDialog.Accepted

        def values(self):
            return ("Bob", "bob@example.com", False)

    monkeypatch.setattr(
        "git_gui.presentation.dialogs.identity_dialog.IdentityDialog",
        _FakeDialog,
    )

    received = []
    getattr(w, signal_name).connect(lambda *_a: received.append(True))
    w._on_commit()

    assert dialog_opened == [True]
    w._commands.set_identity.execute.assert_called_once_with("Bob", "bob@example.com", False)
    assert received == [True]


@pytest.mark.parametrize(
    "state, signal_name",
    [
        ("MERGING", "merge_continue_requested"),
        ("REBASING", "rebase_continue_requested"),
        ("CHERRY_PICKING", "cherry_pick_continue_requested"),
        ("REVERTING", "revert_continue_requested"),
    ],
)
def test_continue_states_skip_when_identity_dialog_cancelled(
    qtbot, monkeypatch, state, signal_name
):
    """If the user cancels the identity dialog, the continue signal must
    NOT be emitted — no commit attempt."""
    w = _make_widget(qtbot)
    w._queries.get_identity.execute.return_value = ("", "")
    w.update_conflict_banner(state)

    class _CancelDialog:
        def __init__(self, *_a, **_kw):
            pass

        def exec(self):
            from PySide6.QtWidgets import QDialog

            return QDialog.Rejected

        def values(self):
            return ("", "", False)

    monkeypatch.setattr(
        "git_gui.presentation.dialogs.identity_dialog.IdentityDialog",
        _CancelDialog,
    )

    received = []
    getattr(w, signal_name).connect(lambda *_a: received.append(True))
    w._on_commit()

    assert received == []
    w._commands.set_identity.execute.assert_not_called()
