"""One place that decides how a hunk is drawn.

Both diff panes ask for a hunk the same way and neither knows which view the
user chose; the preference is read here, once per hunk, at the moment it is
built. That keeps the choice out of three call sites — and it is why toggling
the menu item only has to redraw what is on screen, rather than reach into
anything.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QVBoxLayout, QWidget

from git_gui.domain.entities import Hunk
from git_gui.presentation.app_settings import get_side_by_side_diff
from git_gui.presentation.widgets._collapse_toggle import _CollapseToggle
from git_gui.presentation.widgets.diff_block import DiffFormats, SyntaxFormats, add_hunk_widget
from git_gui.presentation.widgets.side_by_side_block import add_side_by_side_hunk_widget


def add_hunk_view(
    parent_layout: QVBoxLayout,
    hunk: Hunk,
    formats: DiffFormats,
    *,
    extra_left_widgets: list[QWidget] | None = None,
    extra_right_widgets: list[QWidget] | None = None,
    on_header_clicked: Callable[[], None] | None = None,
    syntax_formats: SyntaxFormats | None = None,
    filename: str | None = None,
) -> None:
    """Append one hunk to *parent_layout* in whichever view is preferred."""
    builder = add_side_by_side_hunk_widget if get_side_by_side_diff() else add_hunk_widget
    builder(
        parent_layout,
        hunk,
        formats,
        extra_left_widgets=extra_left_widgets,
        extra_right_widgets=extra_right_widgets,
        on_header_clicked=on_header_clicked,
        syntax_formats=syntax_formats,
        filename=filename,
    )


def hide_hunks_if_collapsed(block_layout: QVBoxLayout) -> None:
    """Hide the hunks of a file block whose chevron says collapsed.

    A block can be collapsed while it is still a skeleton. The collapse hid
    only what the block held then, and hunks realised into it afterwards show
    by default, under a chevron that says they are hidden.
    """
    frame = block_layout.parentWidget()
    toggle = frame.findChild(_CollapseToggle) if frame is not None else None
    if toggle is None or toggle.is_expanded():
        return
    # Item 0 is the file header row, which stays visible to hold the chevron.
    for i in range(1, block_layout.count()):
        item = block_layout.itemAt(i)
        widget = item.widget() if item else None
        if widget is not None:
            widget.setVisible(False)
