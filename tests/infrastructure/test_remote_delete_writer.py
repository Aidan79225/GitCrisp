import subprocess
from types import SimpleNamespace

from git_gui.infrastructure.pygit2 import remote_ops


class _FakeRepo:
    workdir = "/tmp/repo"


def _make_ops():
    ops = remote_ops.RemoteOps.__new__(remote_ops.RemoteOps)
    ops._repo = _FakeRepo()
    ops._git_env = {}
    return ops


def test_delete_remote_branches_parses_push(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return SimpleNamespace(
            returncode=0,
            stdout="To x\n-\t:refs/heads/a\t[deleted]\n-\t:refs/heads/b\t[deleted]\nDone\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    ops = _make_ops()
    results = ops.delete_remote_branches("origin", ["a", "b"])
    assert [r.ok for r in results] == [True, True]
    assert captured["args"][:4] == ["git", "push", "--porcelain", "origin"]
    assert "--delete" in captured["args"]
    assert "refs/heads/a" in captured["args"]


def test_delete_remote_branches_total_failure_uses_stderr(monkeypatch):
    def fake_run(args, **kwargs):
        return SimpleNamespace(
            returncode=128, stdout="", stderr="fatal: could not read from remote"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    ops = _make_ops()
    results = ops.delete_remote_branches("origin", ["a"])
    assert results[0].ok is False
    assert "could not read" in results[0].message


def test_delete_remote_branches_empty_is_noop(monkeypatch):
    def fail(*a, **k):  # must not be called
        raise AssertionError("subprocess.run should not run for empty branches")

    monkeypatch.setattr(subprocess, "run", fail)
    ops = _make_ops()
    assert ops.delete_remote_branches("origin", []) == []
