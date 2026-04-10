"""Tests for the conflict banner in WorkingTreeWidget."""
from __future__ import annotations
import pytest
from PySide6.QtWidgets import QWidget

from git_gui.presentation.widgets.working_tree import WorkingTreeWidget


def _make_widget(qtbot) -> WorkingTreeWidget:
    """Create a WorkingTreeWidget with minimal init bypass."""
    w = WorkingTreeWidget.__new__(WorkingTreeWidget)
    QWidget.__init__(w)
    from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton
    w._conflict_banner = QWidget()
    banner_layout = QHBoxLayout(w._conflict_banner)
    w._banner_label = QLabel("")
    w._btn_abort = QPushButton("Abort")
    w._btn_commit = QPushButton("Commit")
    banner_layout.addWidget(w._banner_label, 1)
    banner_layout.addWidget(w._btn_abort)
    w._conflict_banner.setVisible(False)
    w._btn_abort.clicked.connect(w._on_abort_clicked)
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
