"""Path comparisons the GUI thread can afford."""

from __future__ import annotations

import os


def same_path_text(a: str, b: str) -> bool:
    """Whether two paths are written the same, up to separators and, where the
    file system ignores it, letter case.

    Touches no disk: resolving a path on a share that is down waits out its
    network timeout, with the window frozen.
    """
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))
