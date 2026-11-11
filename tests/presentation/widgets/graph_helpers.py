"""The real GraphWidget without a repository, and fake load workers for it.

For tests that drive the widget directly.
"""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

import pytest

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


class InlineThread:
    """Runs the worker where it was created, so its result lands at once.

    A real worker thread here outlives the test: it emits into a widget qtbot
    has already torn down, which on Windows is heap corruption rather than a
    failure. Nothing in the graph tests needs the work off the main thread.
    """

    def __init__(self, target=None, daemon=None, **kwargs) -> None:
        self._target = target

    def start(self) -> None:
        if self._target is not None:
            self._target()


def fake_graph_threads(
    monkeypatch: pytest.MonkeyPatch, thread_factory: Callable[..., object]
) -> None:
    """Have the graph widget start its load workers through `thread_factory`.

    Only the graph module's own reference to `threading` is swapped, for a
    namespace holding just `Thread`, which is all graph.py uses of it.
    Patching `graph.threading.Thread` instead replaces `threading.Thread`
    for every thread in the process, so the threads subprocess reads git's
    output on (on Windows) are built through the fake and fail with a
    TypeError: at once in a test over a real repository, and in about one
    run in six in the others, when a worker an earlier test left running
    starts one.
    """
    monkeypatch.setattr(
        "git_gui.presentation.widgets.graph.threading", SimpleNamespace(Thread=thread_factory)
    )
