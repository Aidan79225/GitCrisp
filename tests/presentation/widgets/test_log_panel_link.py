"""Tests for LogPanel.log_link — clickable hyperlink rendering."""

from __future__ import annotations

from PySide6.QtWidgets import QTextBrowser

from git_gui.presentation.widgets.log_panel import LogPanel


def test_log_link_appends_hyperlink_html(qtbot):
    panel = LogPanel()
    qtbot.addWidget(panel)
    panel.log_link("New version available: v0.16.0", "https://example.com/r/v0.16.0")
    html = panel._body.toHtml()
    assert "https://example.com/r/v0.16.0" in html
    assert "New version available: v0.16.0" in html
    assert "<a" in html.lower() and "href=" in html.lower()


def test_log_link_escapes_html_in_text(qtbot):
    """A text containing &/< must not break the document."""
    panel = LogPanel()
    qtbot.addWidget(panel)
    panel.log_link("v0.16.0 & friends", "https://example.com/?a=1&b=2")
    plain = panel._body.toPlainText()
    assert "v0.16.0 & friends" in plain  # HTML decodes back to plaintext


def test_log_link_does_not_break_existing_log(qtbot):
    """Existing log()/log_error() output is still readable after refactor."""
    panel = LogPanel()
    qtbot.addWidget(panel)
    panel.log("Plain message")
    panel.log_error("An error")
    panel.log_link("Update available", "https://example.com")
    text = panel._body.toPlainText()
    assert "Plain message" in text
    assert "An error" in text
    assert "Update available" in text


def test_log_panel_body_is_qtextbrowser(qtbot):
    """The body must be a QTextBrowser so links are clickable / openExternalLinks works."""
    panel = LogPanel()
    qtbot.addWidget(panel)
    assert isinstance(panel._body, QTextBrowser)
