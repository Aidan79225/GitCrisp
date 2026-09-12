"""The discard button's icon has to resolve from wherever the app was started.

A packaged GitCrisp runs with its working directory wherever the user launched
it from, not the project root, so a relative icon path finds nothing. That is
not merely a missing icon: Qt warns, the installed message handler runs inside
``_add_hunk_block``, and a windowed build with no stderr turns that warning into
an exception that aborts the whole working-tree diff render.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QtMsgType, qInstallMessageHandler
from PySide6.QtWidgets import QToolButton, QVBoxLayout, QWidget

from git_gui.domain.entities import Hunk
from git_gui.presentation.widgets.hunk_diff import HunkDiffWidget

UNSTAGED_HUNK = Hunk(
    header="@@ -1,2 +1,2 @@",
    lines=[(" ", "one"), ("-", "two"), ("+", "TWO")],
)


@pytest.fixture
def widget(qtbot):
    queries = MagicMock()
    queries.list_submodules.execute.return_value = []
    w = HunkDiffWidget(queries, MagicMock())
    qtbot.addWidget(w)
    return w


@pytest.fixture
def elsewhere(tmp_path):
    """Run the test from a directory that is not the project root."""
    previous = os.getcwd()
    os.chdir(tmp_path)
    yield
    os.chdir(previous)


def _discard_button(host: QWidget) -> QToolButton:
    buttons = host.findChildren(QToolButton)
    assert buttons, "the unstaged hunk block should carry a discard button"
    return buttons[0]


def test_discard_icon_resolves_outside_the_project_root(widget, elsewhere, qtbot):
    """The icon loads even though the working directory holds no arts/."""
    host = QWidget()
    qtbot.addWidget(host)
    layout = QVBoxLayout(host)

    widget._add_hunk_block(
        UNSTAGED_HUNK, is_staged=False, is_untracked=False, path="a.txt", parent_layout=layout
    )

    assert not _discard_button(host).icon().isNull()


def test_building_an_unstaged_hunk_emits_no_qt_warning(widget, elsewhere, qtbot):
    """No Qt message means nothing can be thrown from inside the handler."""
    messages: list[str] = []

    def capture(mode, context, message):
        if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg):
            messages.append(message)

    previous = qInstallMessageHandler(capture)
    try:
        host = QWidget()
        qtbot.addWidget(host)
        layout = QVBoxLayout(host)
        widget._add_hunk_block(
            UNSTAGED_HUNK, is_staged=False, is_untracked=False, path="a.txt", parent_layout=layout
        )
    finally:
        qInstallMessageHandler(previous)

    assert messages == []
