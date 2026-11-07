"""Tests for the QSettings wrapper.

tests/conftest.py gives every test an empty settings store of its own.
"""

from __future__ import annotations


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
