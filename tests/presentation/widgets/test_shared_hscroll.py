"""One horizontal bar for a pane of hunk editors.

Each hunk editor hides both its scrollbars — right for the vertical axis, which
the pane's scroll area owns, but it left long lines reachable only by a
trackpad swipe that moved one hunk and left the rest behind.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QScrollBar, QVBoxLayout, QWidget

from git_gui.presentation.widgets.shared_hscroll import SharedHScroll

LONG = "x" * 500
SHORT = "x"


def _pane(qtbot, texts: list[str]) -> tuple[SharedHScroll, QScrollBar, QWidget, list]:
    """A container of framed hunk editors, as the diff panes build them."""
    container = QWidget()
    layout = QVBoxLayout(container)
    frames = []
    for text in texts:
        frame = QWidget()
        frame_layout = QVBoxLayout(frame)
        editor = QPlainTextEdit()
        editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        editor.setPlainText(text)
        editor.setFixedHeight(60)
        frame_layout.addWidget(editor)
        layout.addWidget(frame)
        frames.append(frame)
    container.resize(300, 300)
    qtbot.addWidget(container)
    container.show()

    bar = QScrollBar()
    qtbot.addWidget(bar)
    sync = SharedHScroll(bar, container)
    sync.refresh()
    return sync, bar, container, frames


def _drop(qtbot, frames, layout_owner) -> None:
    """Tear the blocks down the way a pane clear does, and let Qt finish.

    processEvents alone does not run DeferredDelete, so a plain wait would
    leave the editors alive and the test would prove nothing.
    """
    layout = layout_owner.layout()
    for frame in frames:
        layout.removeWidget(frame)
        frame.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qtbot.wait(50)


# ── The bar appears only when it has something to do ─────────────────────────


def test_no_bar_when_everything_fits(qtbot):
    _sync, bar, _c, _f = _pane(qtbot, [SHORT, SHORT])

    assert not bar.isVisible()
    assert bar.maximum() == 0


def test_the_bar_reaches_as_far_as_the_widest_hunk(qtbot):
    sync, bar, _c, _f = _pane(qtbot, [SHORT, LONG, SHORT])

    assert bar.isVisible()
    widest = max(e.horizontalScrollBar().maximum() for e in sync._editors())
    assert bar.maximum() == widest > 0


def test_the_step_is_one_character(qtbot):
    """Otherwise an arrow key moves by a pixel and the text seems stuck."""
    sync, bar, _c, _f = _pane(qtbot, [LONG])

    assert bar.singleStep() == sync._editors()[0].fontMetrics().horizontalAdvance("0")


# ── Everything moves together ────────────────────────────────────────────────


def test_the_bar_carries_every_hunk_with_it(qtbot):
    sync, bar, _c, _f = _pane(qtbot, [LONG, LONG, LONG])

    bar.setValue(200)

    assert [e.horizontalScrollBar().value() for e in sync._editors()] == [200, 200, 200]


def test_scrolling_one_hunk_brings_the_others(qtbot):
    """A trackpad swipe lands on whichever hunk is under the pointer."""
    sync, bar, _c, _f = _pane(qtbot, [LONG, LONG, LONG])

    sync._editors()[1].horizontalScrollBar().setValue(150)

    assert bar.value() == 150
    assert [e.horizontalScrollBar().value() for e in sync._editors()] == [150, 150, 150]


def test_a_hunk_that_fits_is_not_dragged_off_its_own_edge(qtbot):
    """setValue clamps, so a short hunk simply stays where it is."""
    sync, bar, _c, _f = _pane(qtbot, [SHORT, LONG])

    bar.setValue(bar.maximum())

    short, long_ = sync._editors()
    assert short.horizontalScrollBar().value() == 0
    assert long_.horizontalScrollBar().value() == bar.maximum()


# ── Teardown ─────────────────────────────────────────────────────────────────


def test_the_bar_goes_when_the_pane_is_cleared(qtbot):
    """Blocks die by deleteLater, so the last word has to come after that."""
    sync, bar, container, frames = _pane(qtbot, [LONG, LONG])
    assert bar.isVisible()

    _drop(qtbot, frames, container)

    assert sync._editors() == []
    assert not bar.isVisible()
    assert bar.maximum() == 0


def test_scrolling_after_a_clear_does_not_reach_a_dead_editor(qtbot):
    """A cached editor list would still hold them here, and touching one of
    those raises RuntimeError from the binding rather than failing softly."""
    sync, bar, container, frames = _pane(qtbot, [LONG, LONG])
    _drop(qtbot, frames, container)

    bar.setValue(50)  # must not raise
    sync.refresh()

    assert sync._editors() == []


def test_editors_added_later_join_in(qtbot):
    """Blocks realize lazily as they scroll into view."""
    sync, bar, container, _f = _pane(qtbot, [SHORT])
    assert not bar.isVisible()

    late = QPlainTextEdit()
    late.setLineWrapMode(QPlainTextEdit.NoWrap)
    late.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    late.setPlainText(LONG)
    container.layout().addWidget(late)
    qtbot.waitUntil(lambda: late.width() > 0)
    sync.refresh()

    assert bar.isVisible()
    bar.setValue(bar.maximum())
    assert late.horizontalScrollBar().value() == bar.maximum()


@pytest.mark.parametrize("rounds", [1, 2, 5])
def test_refresh_does_not_stack_duplicate_connections(qtbot, rounds):
    """refresh runs on every render, realize and resize."""
    sync, bar, _c, _f = _pane(qtbot, [LONG])
    for _ in range(rounds):
        sync.refresh()

    seen: list[int] = []
    bar.valueChanged.connect(seen.append)
    sync._editors()[0].horizontalScrollBar().setValue(80)

    assert seen == [80], "the editor should move the bar exactly once"
