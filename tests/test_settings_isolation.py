"""No test may see what another test saved.

The suite points QSettings at a tmp dir so the tests stay out of the
developer's real config. That dir was one for the whole run, and three test
modules each re-pointed QSettings at a tmp dir of their own that outlived
their last test. What one test saved was then still there for every later
test: a Create Tag dialog opened with "Push to origin" ticked or not
depending on what had run before it.

Each pair below leaves something behind in its first test and expects the
second to find nothing. A pair only means something in the order written
here, which is the order pytest runs a module in.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings

from git_gui.presentation.app_settings import get_push_new_tags, set_push_new_tags


def test_a_test_can_save_a_preference():
    set_push_new_tags(True)

    assert get_push_new_tags() is True


def test_the_next_test_starts_with_nothing_saved():
    assert QSettings().allKeys() == []


def test_a_test_can_point_settings_at_a_store_of_its_own(tmp_path):
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    set_push_new_tags(True)

    assert get_push_new_tags() is True


def test_the_next_test_is_not_left_on_that_store():
    assert QSettings().allKeys() == []
