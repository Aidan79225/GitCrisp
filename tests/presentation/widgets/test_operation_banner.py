"""The commit view's banner for a merge, rebase, cherry-pick or revert in progress."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from git_gui.domain.entities import RepoState
from git_gui.presentation.widgets.diff import DiffWidget


@pytest.fixture
def widget(qtbot) -> DiffWidget:
    w = DiffWidget(MagicMock(), MagicMock())
    qtbot.addWidget(w)
    w.show()
    return w


@pytest.mark.parametrize(
    ("state", "abort", "resume"),
    [
        (RepoState.MERGING, "merge_abort_requested", None),
        (RepoState.REBASING, "rebase_abort_requested", "rebase_continue_requested"),
        (
            RepoState.CHERRY_PICKING,
            "cherry_pick_abort_requested",
            "cherry_pick_continue_requested",
        ),
        (RepoState.REVERTING, "revert_abort_requested", "revert_continue_requested"),
    ],
)
def test_each_operation_wires_its_own_abort_and_continue(widget, qtbot, state, abort, resume):
    widget.update_state_banner(state)

    assert widget._state_banner.isVisible()
    assert widget._btn_continue.isVisible() is (resume is not None)
    with qtbot.waitSignal(getattr(widget, abort), timeout=500):
        widget._btn_abort.click()
    if resume is not None:
        with qtbot.waitSignal(getattr(widget, resume), timeout=500):
            widget._btn_continue.click()


@pytest.mark.parametrize("state", [RepoState.CLEAN, RepoState.DETACHED_HEAD])
def test_no_operation_in_progress_hides_the_banner(widget, state):
    widget.update_state_banner(RepoState.REBASING)

    widget.update_state_banner(state)

    assert not widget._state_banner.isVisible()
