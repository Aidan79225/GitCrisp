"""Tests for ViewportBlockLoader."""
from __future__ import annotations
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
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

    # After one tick, only 1 should be realized (serial)
    qtbot.wait(20)
    first_count = len(realized)
    assert first_count >= 1

    # After more ticks, more get realized
    qtbot.wait(200)
    assert len(realized) >= first_count


def test_skips_loaded_paths(qtbot, scroll_area):
    sa, container, layout = scroll_area
    realized = []
    loader = ViewportBlockLoader(sa, lambda path, inner, skel, entry: realized.append(path))

    block = _make_block(layout, "a.txt")
    loader.set_blocks([block])
    loader._loaded_paths.add("a.txt")  # pre-mark as loaded
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
    assert loader._loaded_paths == set()
    assert loader._diff_map == {}
