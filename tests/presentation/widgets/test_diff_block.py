"""Tests for chunked rendering of large hunks in diff_block."""

from __future__ import annotations

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QPlainTextEdit

from git_gui.domain.entities import Hunk
from git_gui.presentation.widgets import diff_block
from git_gui.presentation.widgets.diff_block import (
    make_diff_formats,
    render_hunk_content_lines,
)


def _make_cursor(qtbot):
    edit = QPlainTextEdit()
    qtbot.addWidget(edit)
    return edit.textCursor(), edit


def test_small_hunk_renders_immediately(qtbot):
    """A 50-line hunk is fully rendered in the initial call."""
    lines = [(" ", f"line {i}\n") for i in range(50)]
    hunk = Hunk(header="@@ -1,50 +1,50 @@", lines=lines)
    cursor, edit = _make_cursor(qtbot)
    formats = make_diff_formats()

    render_hunk_content_lines(cursor, hunk, formats)

    assert edit.document().blockCount() >= 50


def test_large_hunk_renders_first_chunk_immediately(qtbot):
    """A 500-line hunk has at least 100 lines rendered immediately."""
    lines = [(" ", f"line {i}\n") for i in range(500)]
    hunk = Hunk(header="@@ -1,500 +1,500 @@", lines=lines)
    cursor, edit = _make_cursor(qtbot)
    formats = make_diff_formats()

    render_hunk_content_lines(cursor, hunk, formats)

    # Immediately after the call, first chunk (100 lines) should be rendered
    assert edit.document().blockCount() >= 100


def test_large_hunk_completes_rendering_after_event_loop(qtbot):
    """A 500-line hunk completes rendering after the event loop processes QTimer callbacks."""
    lines = [(" ", f"line {i}\n") for i in range(500)]
    hunk = Hunk(header="@@ -1,500 +1,500 @@", lines=lines)
    cursor, edit = _make_cursor(qtbot)
    formats = make_diff_formats()

    render_hunk_content_lines(cursor, hunk, formats)

    # Wait for QTimer.singleShot callbacks to fire
    qtbot.wait(200)
    assert edit.document().blockCount() >= 500


def test_chunked_render_canceled_when_widget_deleted(qtbot, monkeypatch):
    """Regression: scheduling chunked rendering then destroying the parent
    QPlainTextEdit must not invoke _render_lines_range against the destroyed
    QTextDocument. Without the QTimer.singleShot context guard, the deferred
    callback dereferences a dangling cursor → EXCEPTION_ACCESS_VIOLATION on
    Windows (faulthandler-confirmed in the wild)."""
    lines = [(" ", f"line {i}\n") for i in range(500)]
    hunk = Hunk(header="@@ -1,500 +1,500 @@", lines=lines)

    calls: list[tuple] = []
    monkeypatch.setattr(
        diff_block,
        "_render_lines_range",
        lambda *args, **kwargs: calls.append(args),
    )

    cursor, edit = _make_cursor(qtbot)
    formats = make_diff_formats()
    render_hunk_content_lines(cursor, hunk, formats)
    assert len(calls) == 1, "first chunk should render synchronously"

    # Destroy the widget (and its QTextDocument). Force the DeferredDelete
    # event to run before the singleShot timer fires.
    edit.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    qtbot.wait(50)

    assert len(calls) == 1, (
        "no chunk should render after the parent widget is deleted; "
        "the QTimer.singleShot context guard must cancel the pending callback"
    )


def test_make_file_block_collapse_hides_non_header_widgets(qtbot):
    """Toggling a file block to collapsed hides every widget inside `inner`
    except the header row at index 0."""
    from PySide6.QtWidgets import QLabel

    from git_gui.presentation.widgets.diff_block import make_file_block

    frame, inner = make_file_block("path/to/file.py")
    qtbot.addWidget(frame)
    # Add two pretend hunk widgets so we can verify they hide.
    hunk1 = QLabel("hunk 1")
    hunk2 = QLabel("hunk 2")
    inner.addWidget(hunk1)
    inner.addWidget(hunk2)

    frame.show()
    qtbot.wait(20)

    # Locate the toggle and verify all three children are visible to start.
    from git_gui.presentation.widgets._collapse_toggle import _CollapseToggle

    toggle = frame.findChild(_CollapseToggle)
    assert toggle is not None
    assert toggle.is_expanded() is True
    assert hunk1.isVisible()
    assert hunk2.isVisible()

    # Collapse — both hunks hide, header stays.
    toggle.click()
    assert toggle.is_expanded() is False
    assert not hunk1.isVisible()
    assert not hunk2.isVisible()
    # Header row (index 0 in inner) is still visible.
    header_widget = inner.itemAt(0).widget()
    assert header_widget is not None
    assert header_widget.isVisible()

    # Expand again — hunks come back.
    toggle.click()
    assert hunk1.isVisible()
    assert hunk2.isVisible()


def test_a_hunk_refits_its_height_when_a_theme_change_brings_a_larger_font(qtbot):
    """A typography change reaches the hunk as a theme change, with the larger
    font already set on the editor; keeping the old height clipped the last
    lines until the commit was selected again."""
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from git_gui.presentation.theme import get_theme_manager
    from git_gui.presentation.widgets.diff_block import add_hunk_widget

    hunk = Hunk(header="@@ -1,10 +1,10 @@", lines=[(" ", f"line {i}\n") for i in range(10)])
    host = QWidget()
    qtbot.addWidget(host)
    add_hunk_widget(QVBoxLayout(host), hunk, make_diff_formats())
    host.show()
    qtbot.waitExposed(host)
    editor = host.findChild(QPlainTextEdit)
    before = editor.height()

    font = editor.font()
    font.setPointSizeF(font.pointSizeF() * 1.5)
    editor.setFont(font)
    manager = get_theme_manager()
    manager.theme_changed.emit(manager.current)

    assert editor.height() > before
    qtbot.waitUntil(lambda: editor.verticalScrollBar().maximum() <= 1)


def _block_in_narrow_pane(qtbot, path: str, header: str):
    """A file block with one hunk and a hunk button, in a 400 px scroll area."""
    from PySide6.QtWidgets import QScrollArea, QToolButton, QVBoxLayout, QWidget

    from git_gui.presentation.widgets.diff_block import add_hunk_widget, make_file_block

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    qtbot.addWidget(scroll)
    container = QWidget()
    layout = QVBoxLayout(container)
    frame, inner = make_file_block(path)
    button = QToolButton()
    hunk = Hunk(header=header, lines=[(" ", "x\n")])
    add_hunk_widget(inner, hunk, make_diff_formats(), extra_right_widgets=[button])
    layout.addWidget(frame)
    scroll.setWidget(container)
    scroll.resize(400, 300)
    scroll.show()
    qtbot.waitExposed(scroll)
    return scroll, container, button


def test_a_long_path_does_not_widen_the_block_past_the_pane(qtbot):
    """A deep monorepo path made the block, and every editor in it, wider than
    the pane, and pushed the hunk's buttons out of view."""
    path = "services/" + "deeply/nested/" * 20 + "SomeVeryLongClassName.java"
    scroll, container, button = _block_in_narrow_pane(qtbot, path, "@@ -1 +1 @@")

    viewport = scroll.viewport()
    assert container.width() <= viewport.width()
    assert button.mapTo(viewport, button.rect().topRight()).x() <= viewport.width()


def test_a_long_hunk_header_does_not_widen_the_block_past_the_pane(qtbot):
    header = "@@ -1 +1 @@ " + "def a_function_with_a_long_signature(argument, " * 8
    scroll, container, _button = _block_in_narrow_pane(qtbot, "a.py", header)

    assert container.width() <= scroll.viewport().width()


def test_a_cut_path_keeps_the_whole_text_in_its_tooltip(qtbot):
    from PySide6.QtWidgets import QLabel

    path = "services/" + "deeply/nested/" * 20 + "SomeVeryLongClassName.java"
    _scroll, container, _button = _block_in_narrow_pane(qtbot, path, "@@ -1 +1 @@")

    labels = [label for label in container.findChildren(QLabel) if path in label.text()]
    assert [label.toolTip() for label in labels] == [f"\U0001f4c4 {path}"]
