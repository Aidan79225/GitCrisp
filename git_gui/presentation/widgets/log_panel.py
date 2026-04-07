# git_gui/presentation/widgets/log_panel.py
from __future__ import annotations
from datetime import datetime
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget
from git_gui.presentation.theme import get_theme_manager, connect_widget


class LogPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._expanded = False

        c = get_theme_manager().current.colors
        self._header = QLabel("▶ Operations Log")
        self._header.setCursor(Qt.PointingHandCursor)
        self._header.mousePressEvent = lambda _: self.toggle()

        self._body = QPlainTextEdit()
        self._body.setReadOnly(True)
        self._body.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._body.setMaximumHeight(150)
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

    def log(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._append(f"[{ts}] {message}", self._fmt_default)

    def log_error(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._append(f"[{ts}] {message}", self._fmt_error)

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
