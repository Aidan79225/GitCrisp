"""Tests for the repo-state tables that pygit2 1.20's constant removal broke.

The removal degraded silently rather than raising, because the constants were
resolved by name with `getattr(pygit2, name, None)` and misses were skipped.
These tests assert the tables are populated, so a future removal fails loudly.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pygit2
import pytest

from git_gui.domain.entities import RepoState
from git_gui.infrastructure.pygit2 import Pygit2Repository
from git_gui.infrastructure.pygit2.repo_state_ops import _REPO_STATE_MAP, REBASE_STATES


def test_state_map_is_not_empty():
    """An empty table maps every state to CLEAN — the exact 1.20 failure."""
    assert _REPO_STATE_MAP


def test_rebase_states_covers_every_flavour_of_rebase():
    assert REBASE_STATES == {
        pygit2.enums.RepositoryState.REBASE,
        pygit2.enums.RepositoryState.REBASE_INTERACTIVE,
        pygit2.enums.RepositoryState.REBASE_MERGE,
        pygit2.enums.RepositoryState.APPLY_MAILBOX_OR_REBASE,
    }


def test_rebase_states_agrees_with_the_state_map():
    """Derived from one table, so the two can't drift apart."""
    assert REBASE_STATES == {
        state for state, mapped in _REPO_STATE_MAP.items() if mapped is RepoState.REBASING
    }


@pytest.mark.skipif(shutil.which("git") is None, reason="drives a real rebase via the git CLI")
def test_a_stopped_rebase_is_recognised(repo_path: Path):
    """The check that went dead: a conflicted rebase must read as a rebase.

    With the table empty, `repo.state() in REBASE_STATES` was always False, so
    interactive_rebase raised git's raw error instead of leaving the conflict
    to the banner.
    """
    raw = pygit2.Repository(str(repo_path))
    sig = pygit2.Signature("Test User", "test@example.com")

    def _commit(content: str, message: str) -> str:
        (repo_path / "conflict.txt").write_text(content)
        raw.index.add("conflict.txt")
        raw.index.write()
        return str(
            raw.create_commit("HEAD", sig, sig, message, raw.index.write_tree(), [raw.head.target])
        )

    base = _commit("base\n", "base")
    _commit("theirs\n", "theirs")
    subprocess.run(["git", "checkout", "-q", "-b", "side", base], cwd=repo_path, check=True)
    _commit("ours\n", "ours")

    proc = subprocess.run(
        ["git", "-c", "user.email=t@e.com", "-c", "user.name=T", "rebase", "master"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0, "the rebase was supposed to conflict"

    state = pygit2.Repository(str(repo_path)).state()
    assert state in REBASE_STATES, f"{state!r} not recognised as a rebase"
    assert Pygit2Repository(str(repo_path)).repo_state().state is RepoState.REBASING
