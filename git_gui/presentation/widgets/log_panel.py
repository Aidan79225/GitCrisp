# git_gui/presentation/widgets/log_panel.py
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDesktopServices, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QLabel, QTextBrowser, QVBoxLayout, QWidget

from git_gui.presentation.theme import connect_widget, get_theme_manager

# Links in the log are either a real URL (the update check posts one) or an
# action for the app to run. A scheme tells them apart, since QTextBrowser hands
# both to the same place.
ACTION_SCHEME = "gitcrisp-action"


class LogPanel(QWidget):
    action_triggered = Signal(str)  # the action id from a clicked log link

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._expanded = False

        c = get_theme_manager().current.colors
        self._header = QLabel("▶ Operations Log")
        self._header.setCursor(Qt.PointingHandCursor)
        self._header.mousePressEvent = lambda _: self.toggle()

        self._body = QTextBrowser()
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

        self._fmt_default = QTextCharFormat()
        self._fmt_default.setForeground(c.as_qcolor("on_surface"))
        self._fmt_error = QTextCharFormat()
        self._fmt_error.setForeground(c.as_qcolor("error"))

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
        self._fmt_default.setForeground(c.as_qcolor("on_surface"))
        self._fmt_error = QTextCharFormat()
        self._fmt_error.setForeground(c.as_qcolor("error"))
        # Recolor existing log lines by reapplying the default format to
        # everything that isn't an error line. We can't tell which is
        # which after the fact, so just normalize the whole document
        # foreground via the document's char format.
        cursor = self._body.textCursor()
        cursor.select(QTextCursor.Document)
        cursor.mergeCharFormat(self._fmt_default)
        cursor.clearSelection()
        self._body.setTextCursor(cursor)

    def log(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._append(f"[{ts}] {message}", self._fmt_default)

    def log_error(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._append(f"[{ts}] {message}", self._fmt_error)

    def log_link(self, message: str, url: str) -> None:
        """Append a single row with ``message`` rendered as a clickable hyperlink to ``url``.

        Both the message text and the URL are HTML-escaped so they cannot
        inject markup. The row uses the timestamp prefix and the theme's
        primary color for the link.
        """
        from html import escape

        ts = datetime.now().strftime("%H:%M:%S")
        safe_msg = escape(message)
        safe_url = escape(url, quote=True)
        c = get_theme_manager().current.colors
        link_color = c.as_qcolor("primary").name()
        on_surface = c.as_qcolor("on_surface").name()
        cursor = self._body.textCursor()
        cursor.movePosition(QTextCursor.End)
        if self._body.document().characterCount() > 1:
            cursor.insertBlock()
        cursor.insertHtml(
            f'<span style="color: {on_surface};">[{ts}] </span>'
            f'<a href="{safe_url}" style="color: {link_color};">{safe_msg}</a>'
        )
        self._body.setTextCursor(cursor)
        self._body.ensureCursorVisible()

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
        from html import escape

        ts = datetime.now().strftime("%H:%M:%S")
        c = get_theme_manager().current.colors
        link_color = c.as_qcolor("primary").name()
        on_surface = c.as_qcolor("on_surface").name()
        href = escape(f"{ACTION_SCHEME}:/{action_id}", quote=True)
        cursor = self._body.textCursor()
        cursor.movePosition(QTextCursor.End)
        if self._body.document().characterCount() > 1:
            cursor.insertBlock()
        cursor.insertHtml(
            f'<span style="color: {on_surface};">[{ts}] {escape(message)}  ·  </span>'
            f'<a href="{href}" style="color: {link_color};">{escape(action_label)}</a>'
        )
        self._body.setTextCursor(cursor)
        self._body.ensureCursorVisible()

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

    def _append(self, text: str, fmt: QTextCharFormat) -> None:
        cursor = self._body.textCursor()
        cursor.movePosition(QTextCursor.End)
        if self._body.document().characterCount() > 1:
            cursor.insertText("\n", fmt)
        cursor.insertText(text, fmt)
        self._body.setTextCursor(cursor)
        self._body.ensureCursorVisible()
