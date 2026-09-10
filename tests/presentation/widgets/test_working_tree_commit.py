"""Tests for commit error surfacing in WorkingTreeWidget._on_commit."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import (
    QCheckBox,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QWidget,
)

from git_gui.presentation.widgets.working_tree import WorkingTreeWidget


def _make_commit_widget(qtbot) -> WorkingTreeWidget:
    """Create a WorkingTreeWidget with minimal init bypass for commit-path tests."""
    w = WorkingTreeWidget.__new__(WorkingTreeWidget)
    QWidget.__init__(w)
    w._msg_edit = QPlainTextEdit()
    w._chk_amend = QCheckBox()
    w._btn_commit = QPushButton("Commit")
    w._draft_msg = ""
    # __init__ is bypassed, so mirror the one signal the commit path relies on.
    w._chk_amend.toggled.connect(w._on_amend_toggled)
    qtbot.addWidget(w)
    return w


def test_on_commit_emits_failed_when_create_commit_raises(qtbot, monkeypatch):
    """When create_commit.execute raises, _on_commit must emit
    commit_failed with the error text and not call reload."""
    queries = MagicMock()
    commands = MagicMock()
    queries.get_identity.execute.return_value = ("Alice", "alice@example.com")
    commands.create_commit.execute.side_effect = RuntimeError("boom")

    w = _make_commit_widget(qtbot)
    w._queries = queries
    w._commands = commands

    received: list[str] = []
    w.commit_failed.connect(lambda reason: received.append(reason))
    reload_called = []
    w.reload_requested.connect(lambda: reload_called.append(True))

    w._msg_edit.setPlainText("test commit message")
    # Simulate a clean repo state.
    w._current_state = "CLEAN"
    w._on_commit()

    assert received == ["Commit failed: boom"]
    assert reload_called == []


# ── Amend ────────────────────────────────────────────────────────────────────


def _amend_widget(qtbot, *, head_message="original subject", remote_on_head=False):
    queries = MagicMock()
    commands = MagicMock()
    queries.get_identity.execute.return_value = ("Alice", "alice@example.com")
    queries.get_head_oid.execute.return_value = "deadbeef"
    queries.get_commit_detail.execute.return_value = SimpleNamespace(message=head_message)
    queries.get_branches.execute.return_value = (
        [SimpleNamespace(name="origin/main", is_remote=True, target_oid="deadbeef")]
        if remote_on_head
        else []
    )
    w = _make_commit_widget(qtbot)
    w._queries = queries
    w._commands = commands
    w._current_state = "CLEAN"
    return w, queries, commands


def test_amend_toggle_prefills_head_message_and_restores_draft(qtbot):
    """Ticking Amend swaps in HEAD's message; unticking gives the draft back."""
    w, _, _ = _amend_widget(qtbot, head_message="original subject")
    w._msg_edit.setPlainText("half-typed draft")

    w._on_amend_toggled(True)
    assert w._msg_edit.toPlainText() == "original subject"
    assert w._btn_commit.text() == "Amend Commit"

    w._on_amend_toggled(False)
    assert w._msg_edit.toPlainText() == "half-typed draft"
    assert w._btn_commit.text() == "Commit"


def test_amend_toggle_on_unborn_branch_bounces_back(qtbot):
    """With no HEAD there is nothing to amend, so the box must not stay ticked."""
    w, queries, _ = _amend_widget(qtbot)
    queries.get_head_oid.execute.return_value = None
    w._chk_amend.setChecked(True)  # setChecked fires the handler

    assert w._chk_amend.isChecked() is False
    assert w._btn_commit.text() == "Commit"


def test_on_commit_routes_to_amend_when_checked(qtbot):
    w, _, commands = _amend_widget(qtbot)
    w._msg_edit.setPlainText("reworded subject")
    w._chk_amend.setChecked(True)
    w._msg_edit.setPlainText("reworded subject")

    w._on_commit()

    commands.amend_commit.execute.assert_called_once_with("reworded subject")
    commands.create_commit.execute.assert_not_called()
    # The box resets so the next commit is a normal one.
    assert w._chk_amend.isChecked() is False


def test_on_commit_creates_normally_when_unchecked(qtbot):
    w, _, commands = _amend_widget(qtbot)
    w._msg_edit.setPlainText("a new commit")

    w._on_commit()

    commands.create_commit.execute.assert_called_once_with("a new commit")
    commands.amend_commit.execute.assert_not_called()


def test_amend_failure_is_surfaced_as_amend_not_commit(qtbot):
    w, _, commands = _amend_widget(qtbot)
    commands.amend_commit.execute.side_effect = RuntimeError("boom")
    w._chk_amend.setChecked(True)

    received: list[str] = []
    w.commit_failed.connect(received.append)
    w._on_commit()

    assert received == ["Amend failed: boom"]


def test_amend_of_pushed_commit_asks_first(qtbot, monkeypatch):
    """A remote ref on HEAD means the commit is published — confirm before rewriting."""
    w, _, commands = _amend_widget(qtbot, remote_on_head=True)
    w._chk_amend.setChecked(True)

    asked: list[str] = []

    def _decline(parent, title, text, *args, **kwargs):
        asked.append(text)
        return QMessageBox.Cancel

    monkeypatch.setattr(QMessageBox, "warning", _decline)
    w._on_commit()

    assert len(asked) == 1
    assert "origin/main" in asked[0]
    commands.amend_commit.execute.assert_not_called()


def test_amend_without_remote_ref_on_head_does_not_ask(qtbot, monkeypatch):
    w, _, commands = _amend_widget(qtbot, remote_on_head=False)
    w._chk_amend.setChecked(True)

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: pytest.fail("should not warn"))
    w._on_commit()

    commands.amend_commit.execute.assert_called_once()


def test_amend_is_disabled_during_a_merge(qtbot):
    """An in-progress merge has its own commit path; Amend must not be reachable."""
    w, _, _ = _amend_widget(qtbot)
    w._conflict_banner = QWidget()
    w._banner_label = QLabel()
    w._chk_amend.setChecked(True)

    w.update_conflict_banner("MERGING")

    assert w._chk_amend.isEnabled() is False
    assert w._chk_amend.isChecked() is False
