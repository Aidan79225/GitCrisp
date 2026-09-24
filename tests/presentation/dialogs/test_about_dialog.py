"""Tests for AboutDialog."""

from __future__ import annotations

from PySide6.QtCore import Qt


def test_version_text_for_release():
    from git_gui.presentation.dialogs.about_dialog import version_text

    assert version_text("1.4.2") == "Version: 1.4.2"
    assert version_text("v1.4.2") == "Version: 1.4.2"


def test_version_text_for_dev_build():
    from git_gui.presentation.dialogs.about_dialog import version_text

    assert version_text("unknown") == "Version: dev build"


def test_dialog_shows_running_version(qtbot, monkeypatch):
    from git_gui.presentation.dialogs import about_dialog

    monkeypatch.setattr(about_dialog, "_get_version", lambda: "2.0.1")
    dlg = about_dialog.AboutDialog()
    qtbot.addWidget(dlg)
    assert dlg._version_label.text() == "Version: 2.0.1"
    assert dlg._version_label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
