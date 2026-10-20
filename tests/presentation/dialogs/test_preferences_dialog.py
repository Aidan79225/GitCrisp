"""Tests for PreferencesDialog."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication, QSettings


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path):
    """Redirect QSettings to a tmp dir and restore Qt globals on teardown."""
    prev_format = QSettings.defaultFormat()
    prev_org = QCoreApplication.organizationName()
    prev_app = QCoreApplication.applicationName()

    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QCoreApplication.setOrganizationName("GitCrispTest")
    QCoreApplication.setApplicationName("GitCrispTest")
    try:
        yield
    finally:
        QSettings.setDefaultFormat(prev_format)
        QCoreApplication.setOrganizationName(prev_org)
        QCoreApplication.setApplicationName(prev_app)


def test_dialog_checkbox_reflects_current_setting_true(qtbot):
    from git_gui.presentation.app_settings import set_check_updates
    from git_gui.presentation.dialogs.preferences_dialog import PreferencesDialog

    set_check_updates(True)
    dlg = PreferencesDialog()
    qtbot.addWidget(dlg)
    assert dlg._check_updates_box.isChecked() is True


def test_dialog_checkbox_reflects_current_setting_false(qtbot):
    from git_gui.presentation.app_settings import set_check_updates
    from git_gui.presentation.dialogs.preferences_dialog import PreferencesDialog

    set_check_updates(False)
    dlg = PreferencesDialog()
    qtbot.addWidget(dlg)
    assert dlg._check_updates_box.isChecked() is False


def test_accept_persists_change(qtbot):
    from git_gui.presentation.app_settings import get_check_updates, set_check_updates
    from git_gui.presentation.dialogs.preferences_dialog import PreferencesDialog

    set_check_updates(True)
    dlg = PreferencesDialog()
    qtbot.addWidget(dlg)
    dlg._check_updates_box.setChecked(False)
    dlg.accept()
    assert get_check_updates() is False


def test_reject_does_not_persist(qtbot):
    from git_gui.presentation.app_settings import get_check_updates, set_check_updates
    from git_gui.presentation.dialogs.preferences_dialog import PreferencesDialog

    set_check_updates(True)
    dlg = PreferencesDialog()
    qtbot.addWidget(dlg)
    dlg._check_updates_box.setChecked(False)
    dlg.reject()
    assert get_check_updates() is True


def test_crash_reports_checkbox_reflects_setting(qtbot):
    from git_gui.presentation.app_settings import set_send_crash_reports
    from git_gui.presentation.dialogs.preferences_dialog import PreferencesDialog

    set_send_crash_reports(False)
    dlg = PreferencesDialog()
    qtbot.addWidget(dlg)
    assert dlg._crash_reports_box.isChecked() is False


def test_accept_persists_and_applies_crash_report_choice(qtbot):
    from git_gui.presentation.app_settings import get_send_crash_reports
    from git_gui.presentation.dialogs.preferences_dialog import PreferencesDialog

    applied: list[bool] = []
    dlg = PreferencesDialog(apply_crash_reporting=applied.append)
    qtbot.addWidget(dlg)
    assert dlg._crash_reports_box.isChecked() is True  # default on
    dlg._crash_reports_box.setChecked(False)
    dlg.accept()
    assert get_send_crash_reports() is False
    assert applied == [False]


def test_reject_leaves_crash_report_choice_alone(qtbot):
    from git_gui.presentation.app_settings import get_send_crash_reports
    from git_gui.presentation.dialogs.preferences_dialog import PreferencesDialog

    applied: list[bool] = []
    dlg = PreferencesDialog(apply_crash_reporting=applied.append)
    qtbot.addWidget(dlg)
    dlg._crash_reports_box.setChecked(False)
    dlg.reject()
    assert get_send_crash_reports() is True
    assert applied == []


def test_accepting_in_a_release_build_does_not_start_sentry(qtbot, monkeypatch):
    """The release job bakes the production DSN in before it runs the suite."""
    import sys
    from types import ModuleType

    import sentry_sdk

    import git_gui
    from git_gui.presentation.dialogs.preferences_dialog import PreferencesDialog

    release_config = ModuleType("git_gui._build_config")
    release_config.DSN = "https://key@example.ingest.sentry.io/1"  # type: ignore[attr-defined]
    release_config.VERSION = "9.9.9"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "git_gui._build_config", release_config)
    monkeypatch.setattr(git_gui, "_build_config", release_config, raising=False)
    started: list[dict] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: started.append(kwargs))

    dlg = PreferencesDialog()
    qtbot.addWidget(dlg)
    dlg.accept()

    assert started == []
