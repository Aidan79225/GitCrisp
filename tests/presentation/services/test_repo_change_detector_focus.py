"""applicationStateChanged → reload propagation."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

from git_gui.presentation.services.repo_change_detector import RepoChangeDetector


def test_application_becoming_active_triggers_reload(qtbot, tmp_path):
    calls: list[None] = []
    d = RepoChangeDetector(str(tmp_path), on_reload=lambda: calls.append(None))

    # Simulate the app gaining focus.
    QGuiApplication.instance().applicationStateChanged.emit(Qt.ApplicationActive)

    qtbot.wait(300)
    assert len(calls) == 1


def test_application_going_inactive_does_not_trigger_reload(qtbot, tmp_path):
    calls: list[None] = []
    d = RepoChangeDetector(str(tmp_path), on_reload=lambda: calls.append(None))

    QGuiApplication.instance().applicationStateChanged.emit(Qt.ApplicationInactive)

    qtbot.wait(300)
    assert calls == []


def test_stop_disconnects_focus_signal(qtbot, tmp_path):
    calls: list[None] = []
    d = RepoChangeDetector(str(tmp_path), on_reload=lambda: calls.append(None))

    d.stop()

    QGuiApplication.instance().applicationStateChanged.emit(Qt.ApplicationActive)
    qtbot.wait(300)
    assert calls == []
