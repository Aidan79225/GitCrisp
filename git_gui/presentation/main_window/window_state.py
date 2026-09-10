# git_gui/presentation/main_window/window_state.py
"""How the user arranged the window — kept across panes and across launches.

The layout was previously a set of constants the app reasserted whenever it
felt like it. Two things followed from that: closing blame or the reflog put
the splitter back to its default, throwing away a drag made minutes earlier,
and nothing at all survived a restart. Both are the same mistake — treating
the arrangement as the app's to decide rather than the user's.

Mixin — not instantiable on its own. Relies on composite-provided attributes
set up by MainWindow's __init__.
"""

from __future__ import annotations

from PySide6.QtWidgets import QSplitter

from git_gui.presentation.app_settings import (
    get_split_sizes,
    get_window_geometry,
    set_split_sizes,
    set_window_geometry,
)

DEFAULT_WINDOW_SIZE = (1400, 800)
DEFAULT_GRAPH_SPLIT = [220, 230, 950]
# Blame and the diff both need room, and the split trades one against the
# other. Measured on a 1600px window: this leaves ~70 columns of code (15% of
# lines needing a horizontal scroll) and ~470px of diff. Giving blame more
# starves the diff it hands off to; less, and a third of the code is off
# screen.
DEFAULT_BLAME_SPLIT = [220, 900, 480]
DEFAULT_SIDEBAR_SPLIT = [400, 400]

# The commit list and blame share a column but want very different amounts of
# it, so the main splitter has a remembered arrangement per mode.
SPLIT_GRAPH = "graph"
SPLIT_BLAME = "blame"
SPLIT_SIDEBAR = "sidebar"


class WindowStateMixin:
    def _restore_window_geometry(self) -> None:
        """Reopen at the size, position and screen the window was closed at."""
        saved = get_window_geometry()
        if saved is None or not self.restoreGeometry(saved):
            self.resize(*DEFAULT_WINDOW_SIZE)

    def _restore_splits(self, splitter: QSplitter, sidebar_splitter: QSplitter) -> None:
        """Take the remembered arrangement, and follow the user's drags from here.

        Sizes rather than QSplitter.saveState: setSizes scales proportionally
        when the window is a different width than it was, which is what should
        happen to a layout described in pixels. restoreState would reinstate
        the old pixel widths and leave the last pane to absorb the difference.
        """
        self._sidebar_splitter = sidebar_splitter
        self._graph_sizes = get_split_sizes(SPLIT_GRAPH) or list(DEFAULT_GRAPH_SPLIT)
        self._blame_sizes = get_split_sizes(SPLIT_BLAME) or list(DEFAULT_BLAME_SPLIT)

        sidebar_splitter.setSizes(get_split_sizes(SPLIT_SIDEBAR) or list(DEFAULT_SIDEBAR_SPLIT))
        splitter.setSizes(self._graph_sizes)

        splitter.splitterMoved.connect(self._remember_split)

    def _remember_split(self, *_args) -> None:
        """Record a drag against whichever pane the column is showing.

        The commit list and blame each keep their own arrangement, so a drag
        made while blame is open must not become the commit list's idea of the
        split — that is what made closing blame feel like it undid your work.
        """
        sizes = self._splitter.sizes()
        if self._left_stack.currentIndex() == 0:
            self._graph_sizes = sizes
        else:
            self._blame_sizes = sizes

    def _save_window_state(self) -> None:
        """Write the arrangement out. Called from MainWindow.closeEvent.

        Deliberately not a closeEvent on this mixin: MainWindow lists
        QMainWindow first, so Python resolves every Qt event handler to the
        Qt base before it ever reaches a mixin. A closeEvent here would look
        right and never run.
        """
        set_window_geometry(self.saveGeometry())
        set_split_sizes(SPLIT_GRAPH, self._graph_sizes)
        set_split_sizes(SPLIT_BLAME, self._blame_sizes)
        set_split_sizes(SPLIT_SIDEBAR, self._sidebar_splitter.sizes())
