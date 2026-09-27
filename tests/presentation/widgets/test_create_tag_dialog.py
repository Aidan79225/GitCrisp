"""Tests for CreateTagDialog's "Push to origin" option."""

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


def _dialog(qtbot, **kwargs):
    from git_gui.presentation.widgets.create_tag_dialog import CreateTagDialog

    dlg = CreateTagDialog(**kwargs)
    qtbot.addWidget(dlg)
    return dlg


def test_push_is_off_by_default(qtbot):
    dlg = _dialog(qtbot)
    assert dlg._push_box.isChecked() is False
    assert dlg.push_requested() is False


def test_push_choice_is_remembered_on_create(qtbot):
    from git_gui.presentation.app_settings import get_push_new_tags

    dlg = _dialog(qtbot)
    dlg._name_edit.setText("v1.0.0")
    dlg._push_box.setChecked(True)
    dlg._on_accept()
    assert dlg.push_requested() is True
    assert get_push_new_tags() is True
    assert _dialog(qtbot)._push_box.isChecked() is True


def test_cancel_does_not_remember_push_choice(qtbot):
    from git_gui.presentation.app_settings import get_push_new_tags

    dlg = _dialog(qtbot)
    dlg._push_box.setChecked(True)
    dlg.reject()
    assert get_push_new_tags() is False


def test_without_origin_push_is_disabled_and_preference_kept(qtbot):
    from git_gui.presentation.app_settings import get_push_new_tags, set_push_new_tags

    set_push_new_tags(True)
    dlg = _dialog(qtbot, can_push=False)
    assert dlg._push_box.isEnabled() is False
    assert dlg.push_requested() is False
    dlg._name_edit.setText("v1.0.0")
    dlg._on_accept()
    assert get_push_new_tags() is True
