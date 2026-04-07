"""Smoke test: every theme-aware widget refreshes on theme_changed.

For each widget:
  1. Build under a qtbot/QApplication fixture.
  2. Spy on its update() method.
  3. Call get_theme_manager().set_mode("light") then set_mode("dark").
  4. Assert update() was called and the widget did not raise.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from git_gui.presentation.theme import get_theme_manager


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def reset_theme():
    """Reset the active theme to dark after each test."""
    yield
    get_theme_manager().set_mode("dark")


def _spy_update(widget) -> list[int]:
    """Replace widget.update with a counting wrapper. Returns the call list."""
    calls: list[int] = []
    original = widget.update

    def wrapped(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    widget.update = wrapped  # type: ignore[method-assign]
    return calls


def test_sidebar_refreshes_on_theme_change(app, reset_theme):
    from git_gui.presentation.widgets.sidebar import SidebarWidget

    widget = SidebarWidget(queries=MagicMock(), commands=MagicMock())
    calls = _spy_update(widget)

    mgr = get_theme_manager()
    mgr.set_mode("light")
    mgr.set_mode("dark")

    assert len(calls) >= 2, f"expected update() to be called at least twice, got {len(calls)}"


def test_working_tree_refreshes_on_theme_change(app, reset_theme):
    from git_gui.presentation.widgets.working_tree import WorkingTreeWidget

    widget = WorkingTreeWidget(queries=MagicMock(), commands=MagicMock())
    calls = _spy_update(widget)

    mgr = get_theme_manager()
    mgr.set_mode("light")
    mgr.set_mode("dark")

    assert len(calls) >= 2


def test_diff_refreshes_on_theme_change(app, reset_theme):
    from git_gui.presentation.widgets.diff import DiffWidget

    widget = DiffWidget(queries=MagicMock(), commands=MagicMock())
    calls = _spy_update(widget)

    mgr = get_theme_manager()
    mgr.set_mode("light")
    mgr.set_mode("dark")

    assert len(calls) >= 2


def test_diff_block_refreshes_on_theme_change(app, reset_theme):
    from git_gui.presentation.widgets.diff_block import make_file_block

    frame, _inner = make_file_block("path/to/file.py")
    calls = _spy_update(frame)

    mgr = get_theme_manager()
    mgr.set_mode("light")
    mgr.set_mode("dark")

    assert len(calls) >= 2
