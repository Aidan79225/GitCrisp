"""Read the UI the way a user reads it — from the models the widgets render.

The e2e tests assert on two sides of every journey: what the widgets show,
and what the on-disk repository actually contains afterwards. These helpers
cover the first side; pygit2 covers the second.
"""

from __future__ import annotations

from pathlib import Path

import pygit2
from PySide6.QtCore import Qt

from git_gui.presentation.models.graph_model import OID_ROLE
from git_gui.presentation.widgets.sidebar import _IS_HEAD_ROLE

# ── What the window shows ────────────────────────────────────────────────


def graph_oids(window) -> list[str]:
    """OIDs of the commit-list rows, top to bottom.

    Includes the synthetic ``WORKING_TREE_OID`` row when the repo is dirty —
    that row is part of what the user sees.
    """
    model = window._graph._model
    return [model.data(model.index(row, 0), OID_ROLE) for row in range(model.rowCount())]


def sidebar_section(window, title: str) -> list[str]:
    """Labels under a sidebar section header (e.g. "LOCAL BRANCHES")."""
    model = window._sidebar._model
    for row in range(model.rowCount()):
        header = model.item(row)
        if header.text() == title:
            return [header.child(i).text() for i in range(header.rowCount())]
    return []


def sidebar_head_branch(window) -> str | None:
    """The local branch the sidebar marks as HEAD, or None."""
    model = window._sidebar._model
    for row in range(model.rowCount()):
        header = model.item(row)
        if header.text() != "LOCAL BRANCHES":
            continue
        for i in range(header.rowCount()):
            child = header.child(i)
            if child.data(_IS_HEAD_ROLE):
                return child.text()
    return None


def working_tree_paths(window) -> list[str]:
    """Paths listed in the working-tree file list."""
    model = window._working_tree._file_model
    return [model.data(model.index(row, 0), Qt.DisplayRole) for row in range(model.rowCount())]


def log_lines(window) -> list[str]:
    """Lines written to the operations log panel."""
    return window._log_panel._body.toPlainText().splitlines()


# ── What the repository on disk actually contains ────────────────────────


def head_oid(repo_dir: Path) -> str:
    return str(pygit2.Repository(str(repo_dir)).head.target)


def head_branch(repo_dir: Path) -> str:
    return pygit2.Repository(str(repo_dir)).head.shorthand


def head_message(repo_dir: Path) -> str:
    return pygit2.Repository(str(repo_dir)).head.peel(pygit2.Commit).message.strip()


def head_tree_paths(repo_dir: Path) -> list[str]:
    tree = pygit2.Repository(str(repo_dir)).head.peel(pygit2.Commit).tree
    return sorted(entry.name for entry in tree)
