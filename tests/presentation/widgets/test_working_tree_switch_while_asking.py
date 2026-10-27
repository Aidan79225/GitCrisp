"""A change confirmed in one repo never runs in the repo opened meanwhile.

A confirmation box or dialog runs a nested event loop. A repo switch that was
already on its way lands inside it and hands the panel the new repo's buses,
but what the user answered was about the repo on screen when they were asked.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QDialog, QMessageBox, QToolButton

from git_gui.domain.entities import Hunk, LineKind, RepoState
from tests.presentation.widgets.hunk_diff_helpers import workers_joined_on_exit
from tests.presentation.widgets.working_tree_helpers import working_tree_widget

SKIPPED = "skipped: another repo opened while you were deciding. Nothing was changed."

EDIT = Hunk(header="@@ -1,2 +1,2 @@", lines=[(LineKind.REMOVED, "b\n"), (LineKind.ADDED, "B\n")])
NEW_FILE = Hunk(header="@@ -0,0 +1,1 @@", lines=[(LineKind.ADDED, "new\n")])


def _buses():
    """A repo whose HEAD has been pushed, and whose changed file shows one edit."""
    queries, commands = MagicMock(), MagicMock()
    queries.get_identity.execute.return_value = ("Alice", "alice@example.com")
    queries.get_head_oid.execute.return_value = "deadbeef"
    queries.get_commit_detail.execute.return_value = SimpleNamespace(message="original subject")
    queries.get_branches.execute.return_value = [
        SimpleNamespace(name="origin/main", is_remote=True, target_oid="deadbeef")
    ]
    queries.list_submodules.execute.return_value = []
    queries.get_staged_diff.execute.return_value = []
    queries.get_file_diff.execute.return_value = [EDIT]
    return queries, commands


@pytest.fixture
def panel(qtbot):
    """The panel open on repo A, its log, and repo B's buses, not yet handed over."""
    with workers_joined_on_exit():
        w = working_tree_widget(qtbot)
        queries_a, commands_a = _buses()
        w.set_buses(queries_a, commands_a)
        reported: list[str] = []
        w.commit_failed.connect(reported.append)
        yield w, commands_a, _buses(), reported


def _answer_yes_once_opened(panel, buses_b):
    """A confirmation box during which repo B finishes opening, then is answered Yes."""

    def _question(*_args, **_kwargs):
        panel.set_buses(*buses_b)
        return QMessageBox.Yes

    return _question


class _IdentityDialogOpeningB:
    """An identity prompt during which repo B finishes opening, then is accepted."""

    def __init__(self, panel, buses_b) -> None:
        self._panel = panel
        self._buses_b = buses_b

    def __call__(self, *_args, **_kwargs):
        return self

    def exec(self):
        self._panel.set_buses(*self._buses_b)
        return QDialog.Accepted

    def values(self):
        return ("Bob", "bob@example.com", False)


def test_an_amend_confirmed_while_another_repo_opened_amends_neither(panel, monkeypatch):
    w, commands_a, buses_b, reported = panel
    w._chk_amend.setChecked(True)
    w._msg_edit.setPlainText("reworded A")

    monkeypatch.setattr(QMessageBox, "warning", _answer_yes_once_opened(w, buses_b))
    w._on_commit()

    commands_a.amend_commit.execute.assert_not_called()
    buses_b[1].amend_commit.execute.assert_not_called()
    assert reported == [f"Amend — {SKIPPED}"]


def test_an_identity_given_while_another_repo_opened_is_saved_to_neither(panel, monkeypatch):
    w, commands_a, buses_b, reported = panel
    w._queries.get_identity.execute.return_value = ("", "")
    w._msg_edit.setPlainText("commit for A")
    monkeypatch.setattr(
        "git_gui.presentation.dialogs.identity_dialog.IdentityDialog",
        _IdentityDialogOpeningB(w, buses_b),
    )

    w._on_commit()

    commands_b = buses_b[1]
    for commands in (commands_a, commands_b):
        commands.set_identity.execute.assert_not_called()
        commands.create_commit.execute.assert_not_called()
    assert reported == [f"Commit — {SKIPPED}"]


def test_a_merge_is_not_continued_in_the_repo_opened_during_the_identity_prompt(panel, monkeypatch):
    w, _, buses_b, reported = panel
    w._queries.get_identity.execute.return_value = ("", "")
    w.update_conflict_banner(RepoState.MERGING, "Merge branch 'feature'")
    continued: list[str] = []
    w.merge_continue_requested.connect(continued.append)
    monkeypatch.setattr(
        "git_gui.presentation.dialogs.identity_dialog.IdentityDialog",
        _IdentityDialogOpeningB(w, buses_b),
    )

    w._on_commit()

    assert continued == []
    assert reported == [f"Commit — {SKIPPED}"]


# ── Discard ──────────────────────────────────────────────────────────────────


def test_a_file_discard_confirmed_while_another_repo_opened_discards_in_neither(panel, monkeypatch):
    w, commands_a, buses_b, reported = panel
    monkeypatch.setattr(QMessageBox, "question", _answer_yes_once_opened(w, buses_b))

    w._discard_file("a.txt")

    commands_a.discard_file.execute.assert_not_called()
    buses_b[1].discard_file.execute.assert_not_called()
    assert reported == [f"Discard a.txt — {SKIPPED}"]


def _discard_button(panel, tooltip: str) -> QToolButton | None:
    buttons = panel._hunk_diff._container.findChildren(QToolButton)
    return next((b for b in buttons if b.toolTip() == tooltip), None)


@pytest.mark.parametrize(
    "hunk, tooltip, command, action",
    [
        (EDIT, "Discard this hunk", "discard_hunk", "Discard hunk in a.txt"),
        (NEW_FILE, "Discard this file", "discard_file", "Discard a.txt"),
    ],
    ids=["hunk", "file"],
)
def test_a_discard_confirmed_in_the_diff_while_another_repo_opened_discards_in_neither(
    qtbot, panel, monkeypatch, hunk, tooltip, command, action
):
    w, commands_a, buses_b, reported = panel
    w._queries.get_file_diff.execute.return_value = [hunk]
    w._hunk_diff.load_file("a.txt")
    qtbot.waitUntil(lambda: _discard_button(w, tooltip) is not None, timeout=2000)
    monkeypatch.setattr(QMessageBox, "question", _answer_yes_once_opened(w, buses_b))

    _discard_button(w, tooltip).click()

    getattr(commands_a, command).execute.assert_not_called()
    getattr(buses_b[1], command).execute.assert_not_called()
    assert reported == [f"{action} — {SKIPPED}"]
