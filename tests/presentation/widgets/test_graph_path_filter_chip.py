"""The file-history chip must fit the commit list, not size it.

A plain label asks for its whole text's width as its minimum. Holding a long
path, it made that the commit list's minimum width, and the splitter gave it
the room by squeezing the diff pane, down to nothing.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from git_gui.presentation.widgets.graph import GraphWidget

LONG_PATH = "src/main/java/com/example/billing/service/impl/InvoiceReconciliationServiceImpl.java"


@pytest.fixture
def graph(qtbot) -> GraphWidget:
    repo_store = MagicMock()
    repo_store.get_repo_setting.return_value = False
    widget = GraphWidget(None, MagicMock(), repo_store=repo_store)
    qtbot.addWidget(widget)
    return widget


def _minimum_width_with(graph: GraphWidget, qtbot, path: str) -> int:
    graph.set_path_filter(path)
    qtbot.wait(10)  # the layout learns of the chip's new text from posted events
    return graph.minimumSizeHint().width()


def test_a_long_path_does_not_widen_the_commit_list(graph, qtbot):
    graph.show()

    with_a_long_path = _minimum_width_with(graph, qtbot, LONG_PATH)

    assert with_a_long_path == _minimum_width_with(graph, qtbot, "a.py")


def test_a_long_path_is_shortened_to_fit_the_chip(graph):
    graph.set_path_filter(LONG_PATH)
    graph.resize(graph.minimumSizeHint().width() + 120, 400)
    graph.show()

    label = graph._path_filter_bar._label
    assert label.fontMetrics().horizontalAdvance(label.text()) <= label.contentsRect().width()
    assert "…" in label.text()


def test_the_whole_path_stays_in_the_tooltip(graph):
    graph.set_path_filter(LONG_PATH)

    assert graph._path_filter_bar._label.toolTip() == LONG_PATH
