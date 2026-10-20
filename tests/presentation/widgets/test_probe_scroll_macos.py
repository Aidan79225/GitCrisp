"""Temporary: the fixed reload test, thirty times on each runner. Not for merging."""

import pytest

from tests.presentation.widgets.test_hunk_diff_scroll_position import (  # noqa: F401
    test_a_reload_keeps_the_same_file_at_the_top,
    widget,
)


@pytest.mark.parametrize("i", range(30))
def test_repeat(widget, qtbot, i):  # noqa: F811
    test_a_reload_keeps_the_same_file_at_the_top(widget, qtbot)
