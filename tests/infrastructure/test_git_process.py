"""run_git: how the infrastructure runs a git command and reads its output."""

from __future__ import annotations

import os
import sys

import pytest

from git_gui.infrastructure.git_process import pinned_git_env, run_git


@pytest.mark.skipif(os.name != "posix", reason="sessions and controlling terminals are POSIX")
def test_git_runs_without_the_terminal_the_app_was_started_from(tmp_path):
    """ssh would ask that terminal for a passphrase while the GUI waits."""
    script = "import os; print(os.getsid(0))"

    result = run_git([sys.executable, "-c", script], cwd=str(tmp_path))

    assert int(result.stdout) != os.getsid(0)


_ELSEWHERE_VARIABLES = ("GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR", "GIT_CONFIG")


def test_git_pinned_to_a_repository_reads_nothing_the_shell_points_elsewhere(monkeypatch):
    """GIT_DIR does not reset the index, objects or config a hook's shell names."""
    for name in _ELSEWHERE_VARIABLES:
        monkeypatch.setenv(name, "elsewhere")

    env = pinned_git_env("repo/.git", "repo")

    assert [name for name in _ELSEWHERE_VARIABLES if name in env] == []
    assert (env["GIT_DIR"], env["GIT_WORK_TREE"]) == ("repo/.git", "repo")
