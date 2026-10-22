"""The real GraphWidget without a repository, for tests that drive it directly."""

from __future__ import annotations

from git_gui.presentation.widgets.graph import GraphWidget


class _NullStore:
    """A repo store with no settings saved, as for a repo never opened before."""

    def get_repo_setting(self, *_args, **_kwargs):
        return None

    def set_repo_setting(self, *_args, **_kwargs):
        pass


def graph_widget(qtbot, queries=None) -> GraphWidget:
    """The real GraphWidget with no repository, answering from `queries`."""
    widget = GraphWidget(queries=queries, commands=None, repo_store=_NullStore())
    qtbot.addWidget(widget)
    return widget
