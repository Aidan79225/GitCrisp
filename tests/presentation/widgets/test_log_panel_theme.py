"""The operations log keeps what each line's colour says across a theme change."""

from __future__ import annotations

import pytest

from git_gui.presentation.theme import get_theme_manager
from git_gui.presentation.widgets.log_panel import LogPanel


@pytest.fixture
def light_then_dark():
    """Start in the light theme; `switch()` moves to dark, as an OS switch would."""
    manager = get_theme_manager()
    original = manager.mode
    manager.set_mode("light")
    yield lambda: manager.set_mode("dark")
    manager.set_mode(original)


def _panel(qtbot) -> LogPanel:
    panel = LogPanel()
    qtbot.addWidget(panel)
    return panel


def _colour_of(panel: LogPanel, text: str) -> str:
    cursor = panel._body.document().find(text)
    assert not cursor.isNull(), f"{text!r} is not in the log"
    return cursor.charFormat().foreground().color().name().lower()


def test_an_error_line_stays_in_the_error_colour(qtbot, light_then_dark):
    """Several failures carry no "ERROR" text; the colour is their only signal."""
    panel = _panel(qtbot)
    panel.log_error("Resolve all conflicts and stage files first")

    light_then_dark()

    error = get_theme_manager().current.colors.error.lower()
    assert _colour_of(panel, "Resolve all conflicts") == error


def test_a_link_stays_in_the_link_colour(qtbot, light_then_dark):
    panel = _panel(qtbot)
    panel.log_action("Reset main", "Undo", "undo-reset")

    light_then_dark()

    accent = get_theme_manager().current.colors.on_primary_container.lower()
    assert _colour_of(panel, "Undo") == accent


def test_a_plain_line_takes_the_new_text_colour(qtbot, light_then_dark):
    panel = _panel(qtbot)
    panel.log("Fetched origin")
    panel.log_action("Reset main", "Undo", "undo-reset")

    light_then_dark()

    on_surface = get_theme_manager().current.colors.on_surface.lower()
    assert _colour_of(panel, "Fetched origin") == on_surface
    assert _colour_of(panel, "Reset main") == on_surface
