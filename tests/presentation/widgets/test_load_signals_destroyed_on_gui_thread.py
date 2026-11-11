"""A load's signals are deleted by Qt on the GUI thread, never by a worker.

Each load hands its worker a signals object to answer through. Parentless, the
object died with its last Python reference, and for a load a newer one had
replaced that reference was the worker's own: the worker thread deleted a
QObject it does not own, which Qt documents as unsafe and which ended a stress
run of back-to-back reloads in heap corruption. A child of the pane that
deletes itself once answered is freed by Qt, on the GUI thread.

The answer of a superseded load can then no longer die with its signals, so
each pane has to drop it itself. And the signals go with the pane, so a worker
finishing after the pane is gone must not fail for it.
"""

from __future__ import annotations

import functools
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from unittest.mock import MagicMock

import pytest
import shiboken6
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from git_gui.domain.entities import Commit, FileDelta, FileStatus, Hunk, LineKind, StagingState
from git_gui.presentation.widgets import diff, hunk_diff, working_tree
from git_gui.presentation.widgets.diff import DiffWidget
from git_gui.presentation.widgets.hunk_diff import HunkDiffWidget
from git_gui.presentation.widgets.working_tree import WorkingTreeWidget
from tests.presentation.thread_helpers import Gate, deliver_queued_answers, recording
from tests.presentation.widgets.hunk_diff_helpers import workers_joined_on_exit


def _hunk(text: str) -> Hunk:
    return Hunk(header="@@ -1,1 +1,1 @@", lines=[(LineKind.ADDED, f"{text}\n")])


def _file(path: str) -> FileStatus:
    return FileStatus(path=path, status=StagingState.UNSTAGED, delta=FileDelta.MODIFIED)


def _spy(monkeypatch, target, name: str, describe: Callable[..., list[str]]) -> list[list[str]]:
    """Record what each call to ``target.name`` was for, and let it go ahead."""
    calls: list[list[str]] = []
    original = getattr(target, name)

    def _recorded(*args):
        calls.append(describe(*args))
        return original(*args)

    monkeypatch.setattr(target, name, _recorded)
    return calls


@dataclass
class _Scenario:
    """A pane given two loads: the first held inside its query, then one that supersedes it."""

    pane: QWidget
    gate: Gate
    load_first: Callable[[], None]
    load_second: Callable[[], None]
    accepted: list[list[str]]  # the paths each answer the pane took in was for
    second: list[str]  # the paths of the second load, the only answer to take in

    def start_first(self) -> threading.Thread:
        """Start the held load; return its worker once it is inside the query."""
        self.load_first()
        return self.gate.held_worker()


def _reload_scenario(monkeypatch, destroyed_on: list[str], *, first_fails: bool) -> _Scenario:
    monkeypatch.setattr(
        working_tree, "_LoadSignals", recording(working_tree._LoadSignals, destroyed_on)
    )
    if first_fails:
        # pytest keeps the log record of the failure; its argument is the
        # exception, whose traceback holds the worker's frame and so its signals.
        monkeypatch.setattr(working_tree.logger, "disabled", True)
    gate = Gate()
    queries = MagicMock()
    queries.get_working_tree_diff_map.execute.return_value = {}
    queries.list_submodules.execute.return_value = []
    reads: list[None] = []

    def _status():
        reads.append(None)
        if len(reads) > 1:
            return [_file("b.txt")]
        gate.hold()
        if first_fails:
            raise OSError("index.lock exists")
        return [_file("a.txt")]

    queries.get_working_tree.execute.side_effect = _status
    pane = WorkingTreeWidget(queries, MagicMock())
    accepted = _spy(
        monkeypatch, pane._file_model, "reload", lambda files, partial: [f.path for f in files]
    )
    return _Scenario(pane, gate, pane.reload, pane.reload, accepted, ["b.txt"])


def _single_file_scenario(monkeypatch, destroyed_on: list[str]) -> _Scenario:
    monkeypatch.setattr(hunk_diff, "_LoadSignals", recording(hunk_diff._LoadSignals, destroyed_on))
    gate = Gate()
    queries = MagicMock()
    queries.list_submodules.execute.return_value = []
    queries.get_staged_diff.execute.return_value = []

    def _file_diff(_oid, path):
        if path == "a.txt":
            gate.hold()
        return [_hunk(path)]

    queries.get_file_diff.execute.side_effect = _file_diff
    pane = HunkDiffWidget(queries, MagicMock())
    accepted = _spy(monkeypatch, pane, "_show_file", lambda path, *_hunks: [path])
    return _Scenario(
        pane,
        gate,
        lambda: pane.load_file("a.txt"),
        lambda: pane.load_file("b.txt"),
        accepted,
        ["b.txt"],
    )


def _all_files_scenario(monkeypatch, destroyed_on: list[str]) -> _Scenario:
    monkeypatch.setattr(
        hunk_diff, "DiffMapSignals", recording(hunk_diff.DiffMapSignals, destroyed_on)
    )
    gate = Gate()
    queries = MagicMock()
    queries.list_submodules.execute.return_value = []

    def _diff_map(paths):
        if paths == ["a.txt"]:
            gate.hold()
        return {path: {StagingState.UNSTAGED: [_hunk(path)]} for path in paths}

    queries.get_working_tree_diff_map.execute.side_effect = _diff_map
    pane = HunkDiffWidget(queries, MagicMock())
    accepted = _spy(monkeypatch, pane._loader, "set_diff_map", lambda diff_map: sorted(diff_map))
    return _Scenario(
        pane,
        gate,
        lambda: pane.load_all_files(["a.txt"]),
        lambda: pane.load_all_files(["b.txt"]),
        accepted,
        ["b.txt"],
    )


FIRST_COMMIT, SECOND_COMMIT = "a" * 40, "b" * 40
COMMIT_FILES = {FIRST_COMMIT: "a.txt", SECOND_COMMIT: "b.txt"}


def _commit_scenario(monkeypatch, destroyed_on: list[str]) -> _Scenario:
    monkeypatch.setattr(diff, "DiffMapSignals", recording(diff.DiffMapSignals, destroyed_on))
    gate = Gate()
    queries = MagicMock()
    queries.get_commit_detail.execute.side_effect = lambda oid: Commit(
        oid=oid, message="m\n", author="A", timestamp=datetime(2026, 1, 1), parents=[]
    )
    queries.get_branches.execute.return_value = []
    queries.list_submodules.execute.return_value = []
    queries.get_commit_files.execute.side_effect = lambda oid: [_file(COMMIT_FILES[oid])]

    def _diff_map(oid):
        if oid == FIRST_COMMIT:
            gate.hold()
        return {COMMIT_FILES[oid]: [_hunk(oid[0])]}

    queries.get_commit_diff_map.execute.side_effect = _diff_map
    pane = DiffWidget(queries, MagicMock())
    accepted = _spy(monkeypatch, pane._loader, "set_diff_map", lambda diff_map: sorted(diff_map))
    return _Scenario(
        pane,
        gate,
        lambda: pane.load_commit(FIRST_COMMIT),
        lambda: pane.load_commit(SECOND_COMMIT),
        accepted,
        ["b.txt"],
    )


# Every place a pane starts a worker and has it answer through a signals object.
SCENARIOS = [
    pytest.param(functools.partial(_reload_scenario, first_fails=False), id="working-tree reload"),
    pytest.param(
        functools.partial(_reload_scenario, first_fails=True), id="working-tree reload that fails"
    ),
    pytest.param(_single_file_scenario, id="single-file load"),
    pytest.param(_all_files_scenario, id="all-files load"),
    pytest.param(_commit_scenario, id="commit diff map"),
]


@pytest.mark.parametrize("make_scenario", SCENARIOS)
def test_a_superseded_loads_signals_are_destroyed_on_the_gui_thread(
    qtbot, monkeypatch, make_scenario
):
    gui_thread = threading.current_thread().name
    destroyed_on: list[str] = []
    with workers_joined_on_exit():
        scenario = make_scenario(monkeypatch, destroyed_on)
        qtbot.addWidget(scenario.pane)
        try:
            first_worker = scenario.start_first()
            scenario.load_second()
            qtbot.waitUntil(lambda: bool(scenario.accepted), timeout=5000)
        finally:
            scenario.gate.open()
        first_worker.join(5)
        assert not first_worker.is_alive()
        deliver_queued_answers()

    assert [name for name in destroyed_on if name != gui_thread] == []
    assert len(destroyed_on) == 2  # one per load: the superseded one's did not outlive its answer
    assert scenario.accepted == [scenario.second]


@pytest.mark.parametrize("make_scenario", SCENARIOS)
def test_a_worker_finishing_after_its_pane_was_destroyed_raises_nothing(monkeypatch, make_scenario):
    raised: list[BaseException | None] = []
    monkeypatch.setattr(threading, "excepthook", lambda args: raised.append(args.exc_value))
    with workers_joined_on_exit():
        scenario = make_scenario(monkeypatch, [])
        try:
            worker = scenario.start_first()
            shiboken6.delete(scenario.pane)  # closed with the load still running
        finally:
            scenario.gate.open()
            if shiboken6.isValid(scenario.pane):  # the load never got going
                shiboken6.delete(scenario.pane)
        worker.join(5)
        assert not worker.is_alive()

    assert raised == []


def _shown_text(widget: HunkDiffWidget) -> str:
    return "".join(e.toPlainText() for e in widget._container.findChildren(QPlainTextEdit))


def test_a_slower_load_of_the_same_file_does_not_replace_the_newer_loads_hunks(qtbot):
    """The pane compared only the path, and both loads are for the same one."""
    gate = Gate()
    reads: list[None] = []

    def _file_diff(_oid, _path):
        reads.append(None)
        if len(reads) > 1:
            return [_hunk("from the newer load")]
        gate.hold()
        return [_hunk("from the slower load")]

    queries = MagicMock()
    queries.list_submodules.execute.return_value = []
    queries.get_staged_diff.execute.return_value = []
    queries.get_file_diff.execute.side_effect = _file_diff
    with workers_joined_on_exit():
        pane = HunkDiffWidget(queries, MagicMock())
        qtbot.addWidget(pane)
        try:
            pane.load_file("a.txt")
            slower_worker = gate.held_worker()
            pane.load_file("a.txt")
            qtbot.waitUntil(lambda: "from the newer load" in _shown_text(pane), timeout=5000)
        finally:
            gate.open()
        slower_worker.join(5)
        assert not slower_worker.is_alive()
        deliver_queued_answers()

    assert "from the slower load" not in _shown_text(pane)
    assert "from the newer load" in _shown_text(pane)
