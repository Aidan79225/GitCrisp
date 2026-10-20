"""The REPOSITORIES title follows a typography scale change without a restart.

It sets its own point size to sit a point under the body text, and the theme
manager keeps a size a widget chose, so the title stayed at the old scale
until the next launch.
"""

from __future__ import annotations

import pytest
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel

from git_gui.presentation.theme import get_theme_manager
from git_gui.presentation.widgets.repo_list import RepoListWidget
from tests.presentation.widgets.test_repo_list_worktrees import _FakeStore


@pytest.fixture
def scale_app_font():
    """Scale the application font as Apply does, and put it back afterwards."""
    app = QApplication.instance()
    original = QFont(app.font())

    def scale(factor: int) -> QFont:
        font = QFont(original)
        font.setPointSize(original.pointSize() * factor)
        app.setFont(font)
        return font

    yield scale
    app.setFont(original)


def _title(widget: RepoListWidget) -> QLabel:
    return next(label for label in widget.findChildren(QLabel) if label.text() == "REPOSITORIES")


def test_the_title_keeps_its_style_at_a_new_typography_scale(qtbot, scale_app_font):
    w = RepoListWidget(_FakeStore())
    qtbot.addWidget(w)

    larger = scale_app_font(2)
    manager = get_theme_manager()
    manager.theme_changed.emit(manager.current)

    font = _title(w).font()
    assert font.pointSize() == larger.pointSize() - 1
    assert font.bold()
