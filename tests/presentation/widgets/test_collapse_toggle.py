"""Tests for _CollapseToggle (reusable chevron toggle button)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from git_gui.presentation.widgets._collapse_toggle import _CollapseToggle


def _app():
    return QApplication.instance() or QApplication([])


def test_initial_state_expanded(qtbot):
    _app()
    toggle = _CollapseToggle(expanded=True)
    qtbot.addWidget(toggle)
    assert toggle.is_expanded() is True
    assert toggle.arrowType() == Qt.DownArrow


def test_initial_state_collapsed(qtbot):
    _app()
    toggle = _CollapseToggle(expanded=False)
    qtbot.addWidget(toggle)
    assert toggle.is_expanded() is False
    assert toggle.arrowType() == Qt.RightArrow


def test_click_toggles_state_and_arrow(qtbot):
    _app()
    toggle = _CollapseToggle(expanded=True)
    qtbot.addWidget(toggle)

    received: list[bool] = []
    toggle.state_changed.connect(lambda s: received.append(s))

    toggle.click()
    assert toggle.is_expanded() is False
    assert toggle.arrowType() == Qt.RightArrow
    assert received == [False]

    toggle.click()
    assert toggle.is_expanded() is True
    assert toggle.arrowType() == Qt.DownArrow
    assert received == [False, True]
