"""A commit's diffs that arrive after another commit was selected."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from git_gui.domain.entities import Commit, FileStatus, Hunk, LineKind
from git_gui.presentation.widgets.diff import DiffWidget


def _hunk(text: str) -> Hunk:
    return Hunk(header="@@ -1 +1 @@", lines=[(LineKind.ADDED, text + "\n")])


def test_a_late_diff_map_for_the_previous_commit_does_not_claim_the_new_blocks(qtbot):
    """The commit view applied whichever fetch finished, so stepping from one
    commit to the next before its diffs arrived marked the new commit's
    blocks as loaded from the old commit's map, and they stayed skeletons."""
    queries = MagicMock()
    queries.get_commit_detail.execute.side_effect = lambda oid: Commit(
        oid=oid, message="m\n", author="A", timestamp=datetime(2026, 1, 1), parents=[]
    )
    queries.get_branches.execute.return_value = []
    queries.list_submodules.execute.return_value = []
    files = {"a" * 40: "a.txt", "b" * 40: "b.txt"}
    queries.get_commit_files.execute.side_effect = lambda oid: [
        FileStatus(path=files[oid], status="staged", delta="modified")
    ]
    queries.get_commit_diff_map.execute.side_effect = lambda oid: {files[oid]: [_hunk(oid[0])]}
    widget = DiffWidget(queries, MagicMock())
    qtbot.addWidget(widget)
    widget.resize(600, 400)
    widget.show()

    with patch("threading.Thread") as thread:
        widget.load_commit("a" * 40)
        widget.load_commit("b" * 40)
    first_fetch, second_fetch = (call.kwargs["target"] for call in thread.call_args_list)

    first_fetch()
    qtbot.wait(100)
    second_fetch()

    def realized() -> bool:
        return widget._loader._block_refs and 0 in widget._loader._realized

    qtbot.waitUntil(realized, timeout=1000)
    _, _, inner, _ = widget._loader._block_refs[0]
    assert inner.count() > 2  # header row + the hunk's header and editor, not a skeleton
