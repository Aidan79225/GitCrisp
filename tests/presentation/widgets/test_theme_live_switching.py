"""Theme-aware widgets follow a live theme switch.

ThemeManager repaints every live widget on a switch, so a widget that paints
from the current theme needs nothing more, and for those this file only
checks that the switch goes through. A widget that bakes token colours into
its stylesheets must rebuild them through the ``rebuild`` it hands
``connect_widget``, or it keeps the old theme's colours until restart; those
are checked on what the rebuild produces.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from git_gui.presentation.theme import get_theme_manager


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def reset_theme():
    """Reset the active theme to dark after each test."""
    yield
    get_theme_manager().set_mode("dark")


def _switch_to_light_then_dark() -> None:
    mgr = get_theme_manager()
    mgr.set_mode("light")
    mgr.set_mode("dark")


def _stylesheets(widget: QWidget) -> str:
    return "\n".join(w.styleSheet() for w in [widget, *widget.findChildren(QWidget)])


def _restyles_with_the_theme(widget: QWidget) -> bool:
    """Whether any stylesheet under `widget` changes between light and dark."""
    mgr = get_theme_manager()
    mgr.set_mode("light")
    light = _stylesheets(widget)
    mgr.set_mode("dark")
    return _stylesheets(widget) != light


def test_a_widget_that_keeps_its_baked_colours_fails_the_check(app, reset_theme):
    """Guards the check itself: ThemeManager's repaint alone must not pass it."""
    label = QLabel()
    label.setStyleSheet(f"color: {get_theme_manager().current.colors.primary};")

    assert not _restyles_with_the_theme(label)


def test_sidebar_survives_a_theme_switch(app, reset_theme, qtbot):
    from git_gui.presentation.widgets.sidebar import SidebarWidget

    qtbot.addWidget(SidebarWidget(queries=MagicMock(), commands=MagicMock()))

    _switch_to_light_then_dark()


def test_working_tree_survives_a_theme_switch(app, reset_theme, qtbot):
    from git_gui.presentation.widgets.working_tree import WorkingTreeWidget

    qtbot.addWidget(WorkingTreeWidget(queries=MagicMock(), commands=MagicMock()))

    _switch_to_light_then_dark()


def test_diff_restyles_on_theme_change(app, reset_theme):
    from git_gui.presentation.widgets.diff import DiffWidget

    widget = DiffWidget(queries=MagicMock(), commands=MagicMock())

    assert _restyles_with_the_theme(widget)


def test_insight_dialog_restyles_on_theme_change(app, reset_theme):
    from git_gui.presentation.widgets.insight_dialog import InsightDialog

    queries = MagicMock()
    queries.get_commit_stats.execute.return_value = []
    dialog = InsightDialog(queries=queries)

    assert _restyles_with_the_theme(dialog)


def test_commit_detail_survives_a_theme_switch(app, reset_theme, qtbot):
    from git_gui.presentation.widgets.commit_detail import CommitDetailWidget

    qtbot.addWidget(CommitDetailWidget())

    _switch_to_light_then_dark()


def test_graph_restyles_on_theme_change(app, reset_theme):
    from git_gui.presentation.widgets.graph import GraphWidget

    repo_store = MagicMock()
    repo_store.get_repo_setting.return_value = False
    widget = GraphWidget(queries=MagicMock(), commands=MagicMock(), repo_store=repo_store)

    assert _restyles_with_the_theme(widget)


def test_repo_list_survives_a_theme_switch(app, reset_theme, qtbot):
    from git_gui.presentation.widgets.repo_list import RepoListWidget

    qtbot.addWidget(RepoListWidget(repo_store=MagicMock()))

    _switch_to_light_then_dark()


def test_clone_dialog_restyles_on_theme_change(app, reset_theme):
    from git_gui.presentation.widgets.clone_dialog import CloneDialog

    dialog = CloneDialog()

    assert _restyles_with_the_theme(dialog)


def test_log_panel_restyles_on_theme_change(app, reset_theme):
    from git_gui.presentation.widgets.log_panel import LogPanel

    widget = LogPanel()

    assert _restyles_with_the_theme(widget)


def test_diff_block_hunk_rerenders_on_theme_change(app, reset_theme):
    from PySide6.QtWidgets import QPlainTextEdit

    from git_gui.domain.entities import Hunk
    from git_gui.presentation.widgets.diff_block import (
        add_hunk_widget,
        make_diff_formats,
        make_file_block,
    )

    frame, inner = make_file_block("example.py")
    hunk = Hunk(
        header="@@ -1,2 +1,2 @@",
        lines=[
            ("-", "old line\n"),
            ("+", "new line\n"),
            (" ", "context\n"),
        ],
    )
    formats = make_diff_formats()
    add_hunk_widget(inner, hunk, formats)

    editors = frame.findChildren(QPlainTextEdit)
    assert len(editors) == 1
    editor = editors[0]

    initial_text = editor.toPlainText()
    assert "old line" in initial_text
    assert "new line" in initial_text

    mgr = get_theme_manager()
    mgr.set_mode("light")
    mgr.set_mode("dark")

    text_after = editor.toPlainText()
    assert "old line" in text_after
    assert "new line" in text_after


def test_diff_block_restyles_on_theme_change(app, reset_theme):
    from git_gui.presentation.widgets.diff_block import make_file_block

    frame, _inner = make_file_block("path/to/file.py")

    assert _restyles_with_the_theme(frame)
