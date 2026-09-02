"""The window's arrangement belongs to the user, not to the app.

Two things used to throw it away: closing blame or the reflog reasserted a
hard-coded split, and nothing survived a restart at all.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QByteArray, QSettings

from git_gui.presentation.app_settings import (
    get_split_sizes,
    get_window_geometry,
    set_split_sizes,
    set_window_geometry,
)
from git_gui.presentation.main_window.window_state import (
    DEFAULT_GRAPH_SPLIT,
    SPLIT_BLAME,
    SPLIT_GRAPH,
    SPLIT_SIDEBAR,
)


@pytest.fixture(autouse=True)
def _clean_settings():
    """Each test starts with nothing saved.

    The suite-wide fixture points QSettings at a tmp dir; this clears what
    earlier tests in the same run left behind.
    """
    QSettings().clear()
    yield
    QSettings().clear()


# ── Storage ──────────────────────────────────────────────────────────────────


def test_nothing_saved_reads_as_absent():
    assert get_window_geometry() is None
    assert get_split_sizes(SPLIT_GRAPH) is None


def test_split_sizes_round_trip():
    set_split_sizes(SPLIT_GRAPH, [220, 230, 950])
    assert get_split_sizes(SPLIT_GRAPH) == [220, 230, 950]


def test_a_one_pane_split_still_reads_back_as_a_list():
    """The ini backend hands a one-element list back as a bare string.

    Encoding the list here rather than handing it to QSettings is what keeps
    that from turning into a str where a list[int] is expected.
    """
    set_split_sizes(SPLIT_SIDEBAR, [400])
    assert get_split_sizes(SPLIT_SIDEBAR) == [400]


def test_window_geometry_round_trips():
    blob = QByteArray(b"\x01\xd9\xd0\xcb not really a geometry")
    set_window_geometry(blob)
    assert get_window_geometry() == blob


@pytest.mark.parametrize("stored", ["", "220,nonsense,950", "220;230;950", "220,-5"])
def test_an_unreadable_split_is_treated_as_absent(stored):
    """A corrupt settings file must not stop the window opening."""
    QSettings().setValue(f"window/split_{SPLIT_GRAPH}", stored)
    assert get_split_sizes(SPLIT_GRAPH) is None


# ── The window ───────────────────────────────────────────────────────────────


def _window(qtbot, repo_path):
    from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
    from git_gui.infrastructure.repo_store import JsonRepoStore
    from git_gui.presentation.main_window import MainWindow
    from main import _open_session

    queries, commands = _open_session(str(repo_path))
    window = MainWindow(
        queries,
        commands,
        JsonRepoStore(),
        JsonRemoteTagCache(),
        str(repo_path),
        session_factory=_open_session,
    )
    qtbot.addWidget(window)
    return window


def test_close_event_reaches_main_window(qtbot, repo_path):
    """Not a formality: a closeEvent on a mixin would never run.

    MainWindow lists QMainWindow first, so Python resolves Qt event handlers
    to the Qt base before any mixin — a save on the mixin would look correct
    and quietly do nothing.
    """
    from git_gui.presentation.main_window import MainWindow

    assert MainWindow.closeEvent.__qualname__ == "MainWindow.closeEvent"


def test_a_drag_while_the_commit_list_is_up_is_the_commit_list_arrangement(qtbot, repo_path):
    w = _window(qtbot, repo_path)

    w._splitter.setSizes([200, 700, 500])
    w._remember_split()

    assert w._graph_sizes == w._splitter.sizes()
    assert w._blame_sizes != w._splitter.sizes(), "blame keeps its own"


def test_a_drag_while_blame_is_up_is_blame_s_arrangement(qtbot, repo_path):
    w = _window(qtbot, repo_path)
    before = list(w._graph_sizes)

    w.open_reflog()  # anything that takes over the commit list's column
    qtbot.waitUntil(lambda: w._left_stack.currentIndex() != 0)
    w._splitter.setSizes([200, 900, 300])
    w._remember_split()

    assert w._blame_sizes == w._splitter.sizes()
    assert w._graph_sizes == before, "a drag in blame must not become the commit list's split"


def test_closing_the_reflog_gives_back_the_users_split_not_the_default(qtbot, repo_path):
    """This is the one that was felt: open the reflog, close it, and the
    splitter you had dragged minutes ago snapped back to a constant.

    Asserting on what the pane asks the splitter for, rather than on the
    sizes that come back: the widgets' own minimum widths dominate at the
    sizes a headless test runs at, which would let the default and the drag
    render identically.
    """
    w = _window(qtbot, repo_path)
    w._splitter.setSizes([200, 700, 500])
    w._remember_split()
    dragged = list(w._graph_sizes)
    assert dragged != DEFAULT_GRAPH_SPLIT, "the drag has to have registered first"

    w.open_reflog()
    qtbot.waitUntil(lambda: w._left_stack.currentIndex() != 0)

    asked_for: list[list[int]] = []
    w._splitter.setSizes = asked_for.append
    w._close_reflog_pane()

    assert asked_for == [dragged]


def test_the_arrangement_survives_a_relaunch(qtbot, repo_path):
    w = _window(qtbot, repo_path)
    w._splitter.setSizes([200, 700, 500])
    w._remember_split()
    saved = list(w._graph_sizes)
    assert saved != DEFAULT_GRAPH_SPLIT, "the drag has to have registered first"
    w._sidebar_splitter.setSizes([500, 300])
    sidebar = w._sidebar_splitter.sizes()

    w.close()

    reopened = _window(qtbot, repo_path)
    assert reopened._graph_sizes == saved
    assert get_split_sizes(SPLIT_SIDEBAR) == sidebar
    assert get_window_geometry() is not None


def test_a_first_run_falls_back_to_the_defaults(qtbot, repo_path):
    w = _window(qtbot, repo_path)

    assert w._graph_sizes == DEFAULT_GRAPH_SPLIT
    assert get_split_sizes(SPLIT_BLAME) is None, "nothing is written until the window closes"
