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
