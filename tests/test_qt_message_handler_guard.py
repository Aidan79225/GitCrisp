"""The suite must keep a Qt message handler installed from first test to last.

On Windows ``QFileSystemWatcher`` waits for changes on a thread of its own,
and that thread logs: when a directory it watches is deleted, which ``git
worktree remove`` does to ``.git/worktrees`` along with the last linked
worktree, it can warn that ``FindNextChangeNotification failed``. A handler
installed from Python is called by PySide6 on whichever thread logs. The call
takes the GIL first and only then reads which function to call, and
``qInstallMessageHandler(None)`` sets that to nothing. pytest-qt installs a
handler for each test and, once the test's call has been reported, puts back
the one it found, which was ``None`` until something had installed one. A
warning from the watcher thread that was still waiting for the GIL at that
moment found no function to call, and the whole pytest process died with an
access violation: a few runs in a hundred of
``test_removing_a_locked_worktree.py`` on Windows, whose first two tests wait
only for the worktree's folder to disappear and so can end before git has
finished.

``tests/conftest.py`` installs a handler before the first test, so what
pytest-qt puts back is a function. It has to be a hook there: pytest-qt's
setup runs before any fixture does, and what a session fixture installed
would be wiped by the first test's put-back.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import qInstallMessageHandler


@pytest.fixture
def handler_in_place_once_pytest_qt_has_stopped_capturing():
    """Check, in its teardown, the handler pytest-qt left for the gap between tests.

    pytest-qt stops capturing when the test's call is reported, which is before
    the fixtures of that test are torn down, so by the time this runs the
    handler is the one pytest-qt put back.
    """
    yield
    in_place = qInstallMessageHandler(lambda _mode, _context, _message: None)
    qInstallMessageHandler(in_place)
    assert in_place is not None, (
        "pytest-qt put back no Qt message handler, so a Qt thread still waiting "
        "for the GIL in PySide6's message-handler callback at that moment finds "
        "no function to call and crashes the process"
    )


def test_a_qt_message_handler_is_still_installed_after_pytest_qt_stops_capturing(
    handler_in_place_once_pytest_qt_has_stopped_capturing,
):
    """The assertion is in the fixture's teardown, where pytest-qt's capture is over."""
