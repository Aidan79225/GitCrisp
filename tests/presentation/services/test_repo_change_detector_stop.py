"""stop() must not wait for Qt's file-watcher thread while holding the GIL.

RepoChangeDetector._release_watches says why. The scenario holds Qt's thread inside its log call
on purpose, instead of racing it (scenario_stop_while_the_watcher_thread_logs.py), and runs in a
process of its own, because a process that hits the bug cannot recover from inside.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import shiboken6

from git_gui.presentation.services.repo_change_detector import RepoChangeDetector

_SCENARIO = Path(__file__).with_name("scenario_stop_while_the_watcher_thread_logs.py")
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
# The scenario takes about two seconds; a process stuck in stop() is given this long before it is
# killed.
_HANG_TIMEOUT_S = 20


def _text(output: str | bytes | None) -> str:
    # A timeout carries what the process had written so far, as bytes on some Python versions.
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output or ""


@pytest.mark.skipif(
    sys.platform != "win32", reason="only Qt's Windows file-watcher thread logs with its lock held"
)
def test_stop_returns_while_the_watcher_thread_is_inside_a_log_call(tmp_path):
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            filter(None, [str(_PROJECT_ROOT), os.environ.get("PYTHONPATH")])
        ),
        "QT_QPA_PLATFORM": "offscreen",
        "PYTHONUTF8": "1",
        # A rule that turns warnings off (QT_LOGGING_RULES from the caller, or a QT_LOGGING_CONF
        # file) would make Qt drop the warning before the scenario's handler sees it, and the test
        # would then blame Qt. Rules in QT_LOGGING_RULES are applied after those of such a file.
        "QT_LOGGING_RULES": "*.warning=true",
    }
    # QT_FATAL_WARNINGS would abort the scenario on that warning.
    env.pop("QT_FATAL_WARNINGS", None)
    try:
        done = subprocess.run(
            [sys.executable, str(_SCENARIO), str(tmp_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=_HANG_TIMEOUT_S,
            env=env,
            cwd=_PROJECT_ROOT,
        )
    except subprocess.TimeoutExpired as hung:
        seen = f"{_text(hung.stdout)}{_text(hung.stderr)}"
        if "holding" in seen:
            pytest.fail(
                f"stop() had not returned after {_HANG_TIMEOUT_S} s: it is waiting for the lock of "
                f"a thread that is waiting for the GIL, and the app is frozen. Output: {seen}"
            )
        pytest.fail(
            f"the scenario had not reached stop() after {_HANG_TIMEOUT_S} s. Output: {seen}"
        )

    output = f"{done.stdout}{done.stderr}"
    assert "Qt did not log" not in done.stdout, (
        "Qt did not log the deleted directory, so nothing held its thread and stop() was not put "
        f"to the test: has Qt's Windows file watcher stopped logging? Output: {output}"
    )
    assert done.returncode == 0, output
    assert "stopped" in done.stdout


def test_stop_deletes_the_watcher(qtbot, repo_path):
    """The test above runs on Windows only; this one pins the deletion on every OS."""
    d = RepoChangeDetector(str(repo_path), on_reload=lambda: None)
    watcher = d._watcher

    d.stop()

    assert not shiboken6.isValid(watcher)
