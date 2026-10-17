"""run_git: how the infrastructure runs a git command and reads its output."""

from __future__ import annotations

import os
import sys

import pytest

from git_gui.infrastructure.git_process import run_git


@pytest.mark.skipif(os.name != "posix", reason="sessions and controlling terminals are POSIX")
def test_git_runs_without_the_terminal_the_app_was_started_from(tmp_path):
    """ssh would ask that terminal for a passphrase while the GUI waits."""
    script = "import os; print(os.getsid(0))"

    result = run_git([sys.executable, "-c", script], cwd=str(tmp_path))

    assert int(result.stdout) != os.getsid(0)
