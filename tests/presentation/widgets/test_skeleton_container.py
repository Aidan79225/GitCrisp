"""The placeholder a file block shows while its diff loads."""

from __future__ import annotations

from git_gui.presentation.theme import get_theme_manager
from git_gui.presentation.widgets.diff_block import make_skeleton_container


def test_the_placeholder_bars_follow_the_theme(qtbot):
    """The bars were a fixed translucent grey that ignored the palette."""
    manager = get_theme_manager()
    manager.set_mode("light")
    try:
        skeleton = make_skeleton_container()
        qtbot.addWidget(skeleton)

        manager.set_mode("dark")

        assert manager.current.colors.outline_variant in skeleton.styleSheet()
    finally:
        manager.set_mode("dark")
