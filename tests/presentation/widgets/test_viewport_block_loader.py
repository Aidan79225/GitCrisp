"""Tests for ViewportBlockLoader."""

from __future__ import annotations

import pytest
import shiboken6
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from git_gui.presentation.widgets.diff_block import (
    make_diff_unavailable_notice,
    make_file_block,
    make_skeleton_container,
)
from git_gui.presentation.widgets.viewport_block_loader import ViewportBlockLoader


@pytest.fixture
def scroll_area(qtbot):
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    container = QWidget()
    layout = QVBoxLayout(container)
    sa.setWidget(container)
    sa.resize(400, 300)
    sa.show()
    qtbot.addWidget(sa)
    return sa, container, layout


def _make_block(layout, path: str, height: int = 60):
    """Create a fake file block frame and add it to the layout."""
    frame = QFrame()
    frame.setFixedHeight(height)
    inner = QVBoxLayout(frame)
    skeleton = QWidget()
    inner.addWidget(skeleton)
    layout.addWidget(frame)
    return (path, frame, inner, skeleton)


def test_set_diff_map_triggers_realize(qtbot, scroll_area):
    sa, container, layout = scroll_area
    realized = []
    loader = ViewportBlockLoader(sa, lambda path, inner, skel, entry: realized.append(path))

    block = _make_block(layout, "a.txt")
    loader.set_blocks([block])
    loader.set_diff_map({"a.txt": ["hunk1"]})

    qtbot.wait(100)  # let QTimer.singleShot fire
    assert "a.txt" in realized


def test_realizes_one_block_per_check(qtbot, scroll_area):
    sa, container, layout = scroll_area
    realized = []
    loader = ViewportBlockLoader(sa, lambda path, inner, skel, entry: realized.append(path))

    blocks = [_make_block(layout, f"f{i}.txt", height=20) for i in range(5)]
    loader.set_blocks(blocks)
    loader.set_diff_map({f"f{i}.txt": [f"hunk{i}"] for i in range(5)})

    # Called directly, before the event loop runs any of the scheduled checks.
    loader._check_viewport()
    assert realized == ["f0.txt"]

    qtbot.waitUntil(lambda: len(realized) == 5)


def test_skips_realized_blocks(qtbot, scroll_area):
    sa, container, layout = scroll_area
    realized = []
    loader = ViewportBlockLoader(sa, lambda path, inner, skel, entry: realized.append(path))

    block = _make_block(layout, "a.txt")
    loader.set_blocks([block])
    loader._realized.add(0)  # pre-mark as realized
    loader.set_diff_map({"a.txt": ["hunk1"]})

    qtbot.wait(100)
    assert "a.txt" not in realized


def test_stale_frame_is_skipped(qtbot, scroll_area):
    sa, container, layout = scroll_area
    realized = []
    loader = ViewportBlockLoader(sa, lambda path, inner, skel, entry: realized.append(path))

    block = _make_block(layout, "a.txt")
    loader.set_blocks([block])

    # Delete the frame to simulate a stale reference
    block[1].deleteLater()
    qtbot.wait(20)

    loader.set_diff_map({"a.txt": ["hunk1"]})
    qtbot.wait(100)
    # Should not crash, and a.txt should not be realized
    assert "a.txt" not in realized


def test_clear_resets_state(qtbot, scroll_area):
    sa, container, layout = scroll_area
    loader = ViewportBlockLoader(sa, lambda *a: None)

    block = _make_block(layout, "a.txt")
    loader.set_blocks([block])
    loader.set_diff_map({"a.txt": ["hunk1"]})

    loader.clear()
    assert loader._block_refs == []
    assert loader._realized == set()
    assert loader._diff_map == {}
    assert not loader._diff_map_arrived


def test_the_loader_and_its_timer_are_freed_with_the_scroll_area(qtbot):
    """Qt frees the loader and its timer with the scroll area, on the GUI thread.

    Parentless, they belonged to Python, and the cyclic collector freed them on
    whichever thread happened to run it, a worker's among them. A timer stopped
    from another thread stays registered with the GUI thread's dispatcher, and
    its next expiry delivers an event to freed memory: the test process dies in
    whichever later test runs an event loop.
    """
    sa = QScrollArea()  # not given to qtbot: this test is the one that deletes it
    loader = ViewportBlockLoader(sa, lambda *a: None)
    timers = loader.findChildren(QTimer)
    assert loader.parent() is sa
    assert timers, "the loader's timer is not its child"

    shiboken6.delete(sa)

    assert not shiboken6.isValid(loader)
    assert not any(shiboken6.isValid(timer) for timer in timers)


def test_two_blocks_for_one_path_are_both_realized(qtbot, scroll_area):
    """A commit that turns a symlink into a file lists the path twice, as a
    deletion and an addition. Tracking realized blocks by path left the
    second one a skeleton for good."""
    sa, container, layout = scroll_area
    realized = []
    loader = ViewportBlockLoader(sa, lambda path, inner, skel, entry: realized.append(skel))

    blocks = [_make_block(layout, "config"), _make_block(layout, "config")]
    loader.set_blocks(blocks)
    loader.set_diff_map({"config": ["hunk"]})

    qtbot.waitUntil(lambda: len(realized) == 2)
    assert realized == [blocks[0][3], blocks[1][3]]


def test_a_hidden_pane_realizes_nothing_until_it_is_shown(qtbot):
    """A page the stack is not showing is never laid out, so every new frame
    sat at (0, 0) and read as on screen: switching the diff view while on the
    working tree built the hidden commit's every block."""
    from PySide6.QtWidgets import QStackedWidget

    stack = QStackedWidget()
    qtbot.addWidget(stack)
    stack.addWidget(QWidget())
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    container = QWidget()
    layout = QVBoxLayout(container)
    sa.setWidget(container)
    stack.addWidget(sa)
    stack.resize(400, 300)
    stack.show()
    qtbot.waitExposed(stack)
    realized = []
    loader = ViewportBlockLoader(sa, lambda path, inner, skel, entry: realized.append(path))
    paths = [f"f{i}.txt" for i in range(20)]
    # Blocks that take their height from their content: a frame fixed at 100px
    # shrinks to its content once the loader releases its height, and more of
    # them would then fit on screen.
    loader.set_blocks([_make_growing_block(layout, path, skeleton_height=100) for path in paths])
    loader.set_diff_map({path: ["hunk"] for path in paths})

    qtbot.wait(200)
    assert realized == []

    stack.setCurrentWidget(sa)
    qtbot.waitUntil(lambda: len(realized) > 0)
    qtbot.wait(200)
    assert len(realized) < len(paths)


def _make_growing_block(layout, path: str, skeleton_height: int = 20):
    """A block whose frame takes the height of its content, as the real ones do."""
    frame = QFrame()
    inner = QVBoxLayout(frame)
    skeleton = QWidget()
    skeleton.setFixedHeight(skeleton_height)
    inner.addWidget(skeleton)
    layout.addWidget(frame)
    return (path, frame, inner, skeleton)


def _make_skeleton_block(layout, path: str):
    """A file block holding the real placeholder, as the panes build them."""
    frame, inner = make_file_block(path)
    skeleton = make_skeleton_container()
    inner.addWidget(skeleton)
    layout.addWidget(frame)
    return (path, frame, inner, skeleton)


def _skeleton_bars(block) -> list[QFrame]:
    return block[1].findChildren(QFrame, "skeletonBar")


def _unavailable_notices(block) -> list[QLabel]:
    return [
        label for label in block[1].findChildren(QLabel) if "could not be loaded" in label.text()
    ]


def _assert_holds_a_notice_not_a_skeleton(block) -> None:
    assert _skeleton_bars(block) == []
    assert len(_unavailable_notices(block)) == 1


def _build_like_a_pane(realized: list[str]):
    """What the panes do with a block that has its diff: swap the skeleton for hunks."""

    def build(path, inner, skeleton, entry):
        realized.append(path)
        inner.removeWidget(skeleton)
        skeleton.deleteLater()

    return build


def test_a_diff_map_that_arrived_empty_replaces_each_skeleton_with_a_notice(qtbot, scroll_area):
    """A diff fetch that failed answers with an empty map. Taking that for a
    map that has not come yet left the placeholder bars up for good."""
    sa, container, layout = scroll_area
    realized: list[str] = []
    loader = ViewportBlockLoader(sa, _build_like_a_pane(realized))
    blocks = [_make_skeleton_block(layout, path) for path in ("a.txt", "b.txt")]
    loader.set_blocks(blocks)

    loader.set_diff_map({})

    def every_block_holds_a_notice() -> None:
        for block in blocks:
            _assert_holds_a_notice_not_a_skeleton(block)

    qtbot.waitUntil(every_block_holds_a_notice, timeout=2000)
    assert realized == []


def test_a_path_missing_from_the_diff_map_gets_a_notice_and_the_others_are_built(
    qtbot, scroll_area
):
    """The working tree's map holds only the paths it could diff: one whose
    change went away meanwhile has no entry, and kept its placeholder bars."""
    sa, container, layout = scroll_area
    realized: list[str] = []
    loader = ViewportBlockLoader(sa, _build_like_a_pane(realized))
    kept, vanished = (_make_skeleton_block(layout, path) for path in ("kept.txt", "vanished.txt"))
    loader.set_blocks([kept, vanished])

    loader.set_diff_map({"kept.txt": ["hunk"]})

    def both_are_settled() -> None:
        assert _skeleton_bars(kept) == []
        _assert_holds_a_notice_not_a_skeleton(vanished)

    qtbot.waitUntil(both_are_settled, timeout=2000)
    assert realized == ["kept.txt"]
    assert _unavailable_notices(kept) == []


def test_the_diff_notice_does_not_point_at_a_log(qtbot):
    """The notice claims only what the code knows: the diff could not be loaded.

    The only log the app shows is the Operations Log, and a failed diff fetch
    reaches only the log file, so a notice saying "see the log" sent the user
    to one that has nothing. Whoever routes failed diff fetches to the
    Operations Log rewords the notice, and this exact match is what tells them to.
    """
    notice = make_diff_unavailable_notice()
    qtbot.addWidget(notice)

    assert notice.text() == "Diff could not be loaded."


def test_a_block_keeps_its_skeleton_until_the_diff_map_arrives(qtbot, scroll_area):
    """Nothing is known about any file before the fetch answers."""
    sa, container, layout = scroll_area
    loader = ViewportBlockLoader(sa, lambda *a: None)
    block = _make_skeleton_block(layout, "a.txt")
    loader.set_blocks([block])

    loader._check_viewport()

    assert len(_skeleton_bars(block)) > 0
    assert _unavailable_notices(block) == []


def test_new_blocks_do_not_inherit_the_diff_map_that_arrived_for_the_old_ones(qtbot, scroll_area):
    sa, container, layout = scroll_area
    loader = ViewportBlockLoader(sa, lambda *a: None)
    old = _make_skeleton_block(layout, "old.txt")
    loader.set_blocks([old])
    loader.set_diff_map({"old.txt": ["hunk"]})
    new = _make_skeleton_block(layout, "new.txt")
    loader.set_blocks([new])

    loader._check_viewport()

    assert len(_skeleton_bars(new)) > 0
    assert _unavailable_notices(new) == []


@pytest.mark.parametrize(
    "diff_map", [{"a.txt": ["hunk"]}, {}], ids=["a block with its diff", "a block with a notice"]
)
def test_a_settled_block_lets_go_of_the_height_a_reload_held_for_it(qtbot, scroll_area, diff_map):
    """A reload keeps a rebuilt block as tall as its last content until it is
    settled, so the user's place survives. Either way a block ends, its own
    content sets the height from then on."""
    sa, container, layout = scroll_area
    loader = ViewportBlockLoader(sa, _build_like_a_pane([]))
    block = _make_skeleton_block(layout, "a.txt")
    block[1].setMinimumHeight(250)
    loader.set_blocks([block])
    loader.set_diff_map(diff_map)

    loader._check_viewport()

    assert block[1].minimumHeight() == 0


def test_a_notice_in_a_collapsed_block_stays_hidden(qtbot, scroll_area):
    """A block can be collapsed while it is still a skeleton. Whatever is put
    in it afterwards has to stay out of sight under the chevron."""
    from git_gui.presentation.widgets._collapse_toggle import _CollapseToggle

    sa, container, layout = scroll_area
    loader = ViewportBlockLoader(sa, lambda *a: None)
    block = _make_skeleton_block(layout, "a.txt")
    loader.set_blocks([block])
    block[1].findChild(_CollapseToggle).click()

    loader.set_diff_map({})

    def holds_a_notice() -> None:
        assert len(_unavailable_notices(block)) == 1

    qtbot.waitUntil(holds_a_notice, timeout=2000)
    assert not _unavailable_notices(block)[0].isVisible()


def test_a_block_pushed_off_screen_by_the_one_just_built_is_not_built(qtbot, scroll_area):
    """Building a block replaces its skeleton with content that is taller, which
    moves every block below. Qt shows the new content a turn later, so a check
    that measures before then sizes the block as if the content were not there
    and reads the blocks below as on screen."""
    sa, container, layout = scroll_area
    realized = []

    def build_tall_first(path, inner, skeleton, entry):
        realized.append(path)
        if path == "f0.txt":
            inner.removeWidget(skeleton)
            skeleton.deleteLater()
            content = QWidget()
            content.setFixedHeight(1000)  # taller than the 300px pane
            inner.addWidget(content)

    loader = ViewportBlockLoader(sa, build_tall_first)
    blocks = [_make_growing_block(layout, f"f{i}.txt") for i in range(5)]
    loader.set_blocks(blocks)
    loader.set_diff_map({f"f{i}.txt": [f"hunk{i}"] for i in range(5)})

    qtbot.wait(300)
    assert realized == ["f0.txt"]
