"""Tests for the QSettings wrapper.

We swap QSettings' storage location to a tmp dir via setPath so tests
don't leak into the developer's real config.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication, QSettings


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path):
    """Redirect QSettings to a tmp dir so tests don't touch the real user config.

    Saves and restores Qt's global state on teardown to avoid leaking
    between test modules in the same pytest process.
    """
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
        # NOTE: QSettings.setPath has no public 'unset'. Restoring the
        # default path requires Qt's internal default; in practice this
        # path leak is harmless because subsequent tests that care about
        # storage also call setPath. Leaving as-is.


def test_get_check_updates_defaults_to_true():
    from git_gui.presentation.app_settings import get_check_updates

    assert get_check_updates() is True


def test_set_then_get_round_trips_false():
    from git_gui.presentation.app_settings import get_check_updates, set_check_updates

    set_check_updates(False)
    assert get_check_updates() is False


def test_set_then_get_round_trips_true():
    from git_gui.presentation.app_settings import get_check_updates, set_check_updates

    set_check_updates(False)
    set_check_updates(True)
    assert get_check_updates() is True
