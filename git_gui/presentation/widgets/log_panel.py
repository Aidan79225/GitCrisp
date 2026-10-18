from __future__ import annotations

from datetime import datetime
from html import escape

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QDesktopServices,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextFragment,
)
from PySide6.QtWidgets import QLabel, QTextBrowser, QVBoxLayout, QWidget

from git_gui.presentation.theme import ColorRole, connect_widget, get_theme_manager

# Links in the log are either a real URL (the update check posts one) or an
# action for the app to run. A scheme tells them apart, since QTextBrowser hands
# both to the same place.
ACTION_SCHEME = "gitcrisp-action"

# Marks the text log_error wrote. A theme change has to give it the new error
# colour, and once written its old colour is all that would tell it apart.
_ERROR_TEXT = QTextFormat.UserProperty


def _fragments(document: QTextDocument) -> list[QTextFragment]:
    fragments = []
    block = document.begin()
    while block.isValid():
        fragments.extend(it.fragment() for it in block)
        block = block.next()
    return fragments


def _timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _colour_role(fmt: QTextCharFormat) -> ColorRole:
    if fmt.isAnchor():
        return ColorRole.ON_PRIMARY_CONTAINER
    if fmt.boolProperty(_ERROR_TEXT):
        return ColorRole.ERROR
    return ColorRole.ON_SURFACE


class LogPanel(QWidget):
    action_triggered = Signal(str)  # the action id from a clicked log link

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._expanded = False

        self._header = QLabel("▶ Operations Log")
        self._header.setCursor(Qt.PointingHandCursor)
        self._header.mousePressEvent = lambda _: self.toggle()

        self._body = QTextBrowser()
        self._body.setAccessibleName("Operations log")
        self._body.setReadOnly(True)
        self._body.setLineWrapMode(QTextBrowser.NoWrap)
        self._body.setMaximumHeight(150)
        # Links are handled here rather than opened blindly: an action link has
        # to reach the app, and a real URL still has to reach the browser.
        self._body.setOpenLinks(False)
        self._body.setOpenExternalLinks(False)
        self._body.anchorClicked.connect(self._on_anchor_clicked)
        font = self._body.font()
        font.setFamily("Courier New")
        self._body.setFont(font)
        self._body.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header)
        layout.addWidget(self._body)

        self._rebuild_styles()
        connect_widget(self, rebuild=self._rebuild_styles)

    def _rebuild_styles(self) -> None:
        c = get_theme_manager().current.colors
        self._header.setStyleSheet(
            f"padding: 4px 8px; background: {c.surface_container}; color: {c.on_surface}; font-weight: bold;"
        )
        self._fmt_default = QTextCharFormat()
        self._fmt_default.setForeground(c.as_qcolor(ColorRole.ON_SURFACE))
        self._fmt_error = QTextCharFormat()
        self._fmt_error.setForeground(c.as_qcolor(ColorRole.ERROR))
        self._fmt_error.setProperty(_ERROR_TEXT, True)
        self._recolour_log()

    def _recolour_log(self) -> None:
        """Give each fragment written so far its role's colour in this theme."""
        colors = get_theme_manager().current.colors
        document = self._body.document()
        # Read every range before writing any: a merge can split or join fragments.
        ranges = [
            (f.position(), f.position() + f.length(), _colour_role(f.charFormat()))
            for f in _fragments(document)
        ]
        cursor = QTextCursor(document)
        cursor.beginEditBlock()
        for start, end, role in ranges:
            fmt = QTextCharFormat()
            fmt.setForeground(colors.as_qcolor(role))
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.KeepAnchor)
            cursor.mergeCharFormat(fmt)
        cursor.endEditBlock()

    def log(self, message: str) -> None:
        self._append(f"[{_timestamp()}] {message}", self._fmt_default)

    def log_error(self, message: str) -> None:
        self._append(f"[{_timestamp()}] {message}", self._fmt_error)

    def log_link(self, message: str, url: str) -> None:
        """Append a single row with ``message`` rendered as a clickable hyperlink to ``url``.

        Both the message text and the URL are HTML-escaped so they cannot
        inject markup. The row uses the timestamp prefix and the theme's
        on_primary_container color for the link.
        """
        self._append_link_row("", url, message)

    def _on_anchor_clicked(self, url) -> None:
        if url.scheme() == ACTION_SCHEME:
            self.action_triggered.emit(url.path().lstrip("/") or url.host())
            return
        QDesktopServices.openUrl(url)

    def log_action(self, message: str, action_label: str, action_id: str) -> None:
        """Log `message` with a trailing link that runs `action_id` when clicked.

        This is where an undo belongs: right after the operation, on the line
        that reports it, where the reader is already looking. A permanent
        control would have to be found; this one arrives.
        """
        self._append_link_row(f"{message}  ·  ", f"{ACTION_SCHEME}:/{action_id}", action_label)

    def expand(self) -> None:
        self._expanded = True
        self._body.setVisible(True)
        self._header.setText("▼ Operations Log")

    def collapse(self) -> None:
        self._expanded = False
        self._body.setVisible(False)
        self._header.setText("▶ Operations Log")

    def toggle(self) -> None:
        if self._expanded:
            self.collapse()
        else:
            self.expand()

    def _append_link_row(self, prefix: str, href: str, label: str) -> None:
        """A timestamped row of `prefix` text ending in a themed link to `href`."""
        c = get_theme_manager().current.colors
        link_color = c.as_qcolor(ColorRole.ON_PRIMARY_CONTAINER).name()
        on_surface = c.as_qcolor(ColorRole.ON_SURFACE).name()
        self._append_html(
            f'<span style="color: {on_surface};">[{_timestamp()}] {escape(prefix)}</span>'
            f'<a href="{escape(href, quote=True)}" style="color: {link_color};">'
            f"{escape(label)}</a>"
        )

    def _append_html(self, html: str) -> None:
        cursor = self._body.textCursor()
        cursor.movePosition(QTextCursor.End)
        if self._body.document().characterCount() > 1:
            cursor.insertBlock()
        cursor.insertHtml(html)
        self._body.setTextCursor(cursor)
        self._body.ensureCursorVisible()

    def _append(self, text: str, fmt: QTextCharFormat) -> None:
        cursor = self._body.textCursor()
        cursor.movePosition(QTextCursor.End)
        if self._body.document().characterCount() > 1:
            cursor.insertText("\n", fmt)
        cursor.insertText(text, fmt)
        self._body.setTextCursor(cursor)
        self._body.ensureCursorVisible()
