"""The menu item that makes the two-pane diff reachable.

Two things have to hold for the feature to work at all: the hunk builders have
to read the preference at the moment they draw, and toggling the menu has to
redraw what is already on screen — a preference nothing acts on until the next
click reads as broken.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMainWindow, QPlainTextEdit, QVBoxLayout, QWidget

from git_gui.domain.entities import Hunk
from git_gui.presentation.app_settings import get_side_by_side_diff, set_side_by_side_diff
from git_gui.presentation.menus.appearance import install_appearance_menu
from git_gui.presentation.menus.view_menu import install_diff_view_menu, view_menu
from git_gui.presentation.widgets.diff_block import make_diff_formats
from git_gui.presentation.widgets.hunk_view import add_hunk_view

HUNK = Hunk(
    header="@@ -1,2 +1,2 @@",
    lines=[("-", "old\n"), ("+", "new\n")],
)


@pytest.fixture(autouse=True)
def _clean_settings():
    QSettings().clear()
    yield
    QSettings().clear()


def _action(window: QMainWindow, label: str):
    for action in view_menu(window).actions():
        if action.text().replace("&", "").rstrip(".") == label:
            return action
    return None


def _drawn(qtbot, hunk: Hunk = HUNK) -> list[QPlainTextEdit]:
    host = QWidget()
    qtbot.addWidget(host)
    add_hunk_view(QVBoxLayout(host), hunk, make_diff_formats())
    return host.findChildren(QPlainTextEdit)


# ── The preference ───────────────────────────────────────────────────────────


def test_unified_is_the_default():
    """It is what the app has always shown, and the better view in a narrow
    window — two columns there leave neither side readable."""
    assert get_side_by_side_diff() is False


def test_the_preference_round_trips():
    set_side_by_side_diff(True)
    assert get_side_by_side_diff() is True


# ── What gets drawn ──────────────────────────────────────────────────────────


def test_a_hunk_is_drawn_unified_by_default(qtbot):
    assert len(_drawn(qtbot)) == 1


def test_a_hunk_is_drawn_as_two_panes_when_the_preference_is_set(qtbot):
    set_side_by_side_diff(True)

    assert len(_drawn(qtbot)) == 2


def test_the_preference_is_read_at_draw_time_not_at_import(qtbot):
    """Both panes build hunks long after the module loaded, so a value cached
    at import would leave the first commit drawn the old way."""
    assert len(_drawn(qtbot)) == 1
    set_side_by_side_diff(True)
    assert len(_drawn(qtbot)) == 2
    set_side_by_side_diff(False)
    assert len(_drawn(qtbot)) == 1


def test_the_staging_checkbox_and_syntax_reach_either_view(qtbot):
    """The working tree hands the builder a checkbox and the filename. Dropping
    either on the way through would cost per-hunk staging or the colouring, and
    only in one of the two views."""
    from unittest.mock import patch

    from git_gui.presentation.widgets.diff_block import make_syntax_formats

    box = QWidget()
    qtbot.addWidget(box)
    syntax = make_syntax_formats()

    for preference, target in ((False, "add_hunk_widget"), (True, "add_side_by_side_hunk_widget")):
        set_side_by_side_diff(preference)
        with patch(f"git_gui.presentation.widgets.hunk_view.{target}") as builder:
            host = QWidget()
            qtbot.addWidget(host)
            add_hunk_view(
                QVBoxLayout(host),
                HUNK,
                make_diff_formats(),
                extra_left_widgets=[box],
                syntax_formats=syntax,
                filename="x.py",
            )
        kwargs = builder.call_args.kwargs
        assert kwargs["extra_left_widgets"] == [box]
        assert kwargs["syntax_formats"] is syntax
        assert kwargs["filename"] == "x.py"


# ── The menu ─────────────────────────────────────────────────────────────────


def test_the_toggle_lands_in_the_same_view_menu_as_appearance(qtbot):
    """A second "View" beside the first is what looking the menu up by its
    label would produce."""
    window = QMainWindow()
    qtbot.addWidget(window)
    install_appearance_menu(window)
    install_diff_view_menu(window, lambda: None)

    titles = [a.text().replace("&", "") for a in window.menuBar().actions()]
    assert titles.count("View") == 1
    assert _action(window, "Appearance") is not None
    assert _action(window, "Side-by-side diff") is not None


def test_the_toggle_opens_showing_the_saved_choice(qtbot):
    set_side_by_side_diff(True)
    window = QMainWindow()
    qtbot.addWidget(window)
    install_diff_view_menu(window, lambda: None)

    assert _action(window, "Side-by-side diff").isChecked()


def test_installing_does_not_redraw(qtbot):
    """setChecked emits toggled, and a redraw fired during _build_chrome would
    reach panes the window has not built yet."""
    set_side_by_side_diff(True)
    redraws: list[int] = []
    window = QMainWindow()
    qtbot.addWidget(window)

    install_diff_view_menu(window, lambda: redraws.append(1))

    assert redraws == []


def test_toggling_writes_the_preference_and_redraws(qtbot):
    redraws: list[bool] = []
    window = QMainWindow()
    qtbot.addWidget(window)
    install_diff_view_menu(window, lambda: redraws.append(get_side_by_side_diff()))

    _action(window, "Side-by-side diff").trigger()

    assert get_side_by_side_diff() is True
    assert redraws == [True], "the redraw has to see the new value, not the old one"


def test_toggling_back_returns_to_unified(qtbot):
    set_side_by_side_diff(True)
    window = QMainWindow()
    qtbot.addWidget(window)
    install_diff_view_menu(window, lambda: None)

    _action(window, "Side-by-side diff").trigger()

    assert get_side_by_side_diff() is False


# ── The panes redraw ─────────────────────────────────────────────────────────


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


def test_the_menu_redraws_both_panes(qtbot, repo_path, monkeypatch):
    """The working tree is one click away from the commit diff; leaving it
    drawn the old way is the same bug, one click later."""
    window = _window(qtbot, repo_path)
    redrawn: list[str] = []
    monkeypatch.setattr(window._diff, "refresh_view", lambda: redrawn.append("commit"))
    monkeypatch.setattr(
        window._working_tree, "refresh_diff_view", lambda: redrawn.append("working tree")
    )

    _action(window, "Side-by-side diff").trigger()

    assert sorted(redrawn) == ["commit", "working tree"]


def test_the_working_tree_keeps_its_selection_across_a_redraw(qtbot, repo_path):
    """Redrawing by reloading the file list would drop the file you were
    reading and land you back on the aggregate view."""
    window = _window(qtbot, repo_path)
    pane = window._working_tree._hunk_diff
    loaded: list[object] = []
    pane.load_file = loaded.append

    pane._current_path = "some/file.py"
    pane._all_paths = None
    window._working_tree.refresh_diff_view()

    assert loaded == ["some/file.py"]


def test_the_commit_pane_redraws_nothing_when_no_commit_is_selected(qtbot, repo_path):
    window = _window(qtbot, repo_path)
    window._diff._current_oid = None
    loaded: list[object] = []
    window._diff.load_commit = loaded.append

    window._diff.refresh_view()

    assert loaded == []
