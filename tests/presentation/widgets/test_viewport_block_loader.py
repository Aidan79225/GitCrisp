"""Tests for ViewportBlockLoader."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

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
