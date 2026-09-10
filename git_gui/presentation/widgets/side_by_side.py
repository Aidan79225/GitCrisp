# git_gui/presentation/widgets/side_by_side.py
"""Turn a unified hunk into the rows a two-pane diff draws.

A unified hunk is one column: every deletion of a change, then every addition,
in the order the diff emitted them. Two panes need a different shape — a list
of rows, each holding a cell on the left, on the right, or on both — and the
interesting part is what happens when the two sides are not the same length.
Three lines removed and five added is one change, and it has to occupy five
rows with the left side blank for the last two; anything else lets the two
panes drift apart for the rest of the hunk.

So a run of removals and additions is paired row by row and the shorter side is
padded, and a context line closes the run: it belongs to both sides at once and
nothing may pair across it.

Nothing here draws. The rows carry the line numbers each side shows and whether
a cell is part of a change, which is all the renderer needs to colour them; a
row whose two cells are both changed is a modified line, and that is where a
word-level diff belongs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from git_gui.domain.entities import Hunk


@dataclass(frozen=True)
class Cell:
    """One line as it appears on one side of the view."""

    number: int  # the line number that side shows for it
    text: str  # without the trailing newline
    changed: bool  # part of a change, rather than context shared by both sides


# The left and right of one row. A side is None where that side has nothing:
# the padding under a shorter run, or a line that only ever existed on one side.
Row = tuple[Cell | None, Cell | None]


_HEADER_RE = re.compile(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def parse_hunk_header(header: str) -> tuple[int, int]:
    """Return (old_start, new_start) line numbers parsed from a @@ header string."""
    m = _HEADER_RE.match(header)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 1, 1


def align_hunk(hunk: Hunk) -> list[Row]:
    """Lay *hunk* out as left/right rows, padding the shorter side of a change.

    Origins other than "-" and "+" count as context, which is how the unified
    renderer already treats them: git marks "no newline at end of file" and the
    end-of-file variants with their own characters, and those lines are still
    part of both sides.
    """
    old_number, new_number = parse_hunk_header(hunk.header)
    rows: list[Row] = []
    removed: list[Cell] = []
    added: list[Cell] = []

    def close_run() -> None:
        for i in range(max(len(removed), len(added))):
            rows.append(
                (
                    removed[i] if i < len(removed) else None,
                    added[i] if i < len(added) else None,
                )
            )
        removed.clear()
        added.clear()

    for origin, content in hunk.lines:
        text = content.rstrip("\n")
        if origin == "-":
            removed.append(Cell(number=old_number, text=text, changed=True))
            old_number += 1
        elif origin == "+":
            added.append(Cell(number=new_number, text=text, changed=True))
            new_number += 1
        else:
            close_run()
            rows.append(
                (
                    Cell(number=old_number, text=text, changed=False),
                    Cell(number=new_number, text=text, changed=False),
                )
            )
            old_number += 1
            new_number += 1

    close_run()
    return rows
