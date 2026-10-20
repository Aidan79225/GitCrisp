"""The suite must never ask GitHub for the latest release.

The release workflow bakes the tag into ``_build_config`` before it runs the
suite, and ``MainWindow.__init__`` starts the update check whenever a version
is known. Every test that built a window then sent an unauthenticated request
to the releases API from each release runner, and on a hotfix tag older than
the latest release the update link expanded the log under tests that assert
it is collapsed.
"""

from __future__ import annotations

import threading
import urllib.request

import git_gui.observability as obs
from tests.presentation.window_helpers import blank_window


def test_a_window_on_a_release_build_never_asks_github_for_updates(qtbot, monkeypatch):
    monkeypatch.setattr(obs, "_get_baked_config", lambda: (None, "9.9.9"))
    requested = threading.Event()

    def _record_request(*args, **kwargs):
        requested.set()
        raise OSError("the suite must stay offline")

    monkeypatch.setattr(urllib.request, "urlopen", _record_request)

    blank_window(qtbot)

    assert not requested.wait(timeout=0.5)
