"""Unit tests for CollapsingHeader — the parallax-shrink container
around commit detail + commit message in DiffWidget."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QPlainTextEdit

from git_gui.presentation.widgets.collapsing_header import CollapsingHeader
from git_gui.presentation.widgets.commit_detail import CommitDetailWidget


@pytest.fixture
def header(qtbot):
    detail = CommitDetailWidget()
    msg = QPlainTextEdit()
    h = CollapsingHeader(detail, msg)
    qtbot.addWidget(h)
    return h, detail, msg


def test_expanded_progress_zero_sets_full_height(header):
    h, _, _ = header
    h.set_expanded_height(200)
    h.set_collapse_progress(0.0)
    assert h.maximumHeight() == 200


def test_fully_collapsed_progress_one_sets_zero_height(header):
    h, _, _ = header
    h.set_expanded_height(200)
    h.set_collapse_progress(1.0)
    assert h.maximumHeight() == 0


def test_half_progress_sets_half_height(header):
    h, _, _ = header
    h.set_expanded_height(200)
    h.set_collapse_progress(0.5)
    assert h.maximumHeight() == 100


def test_progress_below_zero_clamps(header):
    h, _, _ = header
    h.set_expanded_height(200)
    h.set_collapse_progress(-0.3)
    assert h.collapse_progress() == 0.0
    assert h.maximumHeight() == 200


def test_progress_above_one_clamps(header):
    h, _, _ = header
    h.set_expanded_height(200)
    h.set_collapse_progress(2.0)
    assert h.collapse_progress() == 1.0
    assert h.maximumHeight() == 0


def test_zero_expanded_height_gives_zero_max_regardless_of_progress(header):
    h, _, _ = header
    h.set_expanded_height(0)
    h.set_collapse_progress(0.0)
    assert h.maximumHeight() == 0
    h.set_collapse_progress(0.5)
    assert h.maximumHeight() == 0


def test_changing_expanded_height_reapplies_current_progress(header):
    h, _, _ = header
    h.set_expanded_height(200)
    h.set_collapse_progress(0.5)
    assert h.maximumHeight() == 100

    h.set_expanded_height(400)
    # progress is still 0.5 → max height should be 400 * 0.5 = 200
    assert h.maximumHeight() == 200


def test_negative_expanded_height_clamps_to_zero(header):
    h, _, _ = header
    h.set_expanded_height(-100)
    assert h.expanded_height() == 0
    assert h.maximumHeight() == 0


def test_children_are_reparented_into_header(header):
    h, detail, msg = header
    # Both children should now have the header as their parent.
    assert detail.parent() is h
    assert msg.parent() is h


def test_initial_state_has_zero_max_height(qtbot):
    """Before set_expanded_height is ever called, the header collapses to 0
    rather than showing its children at uncontrolled sizes."""
    detail = CommitDetailWidget()
    msg = QPlainTextEdit()
    h = CollapsingHeader(detail, msg)
    qtbot.addWidget(h)
    assert h.maximumHeight() == 0
    assert h.expanded_height() == 0
    assert h.collapse_progress() == 0.0
