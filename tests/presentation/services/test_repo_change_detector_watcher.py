"""QFileSystemWatcher set-up and fileChanged → reload propagation."""

from __future__ import annotations

from PySide6.QtCore import qInstallMessageHandler

from git_gui.presentation.services.repo_change_detector import RepoChangeDetector


def test_detector_watches_git_head_and_refs_heads(qtbot, repo_path):
    """Given a real temp git repo (from conftest), the detector should
    register at least HEAD and refs/heads/ as watch targets."""
    calls: list[None] = []
    d = RepoChangeDetector(str(repo_path), on_reload=lambda: calls.append(None))

    watched_files = set(d._watcher.files())
    watched_dirs = set(d._watcher.directories())

    assert any(f.endswith("HEAD") for f in watched_files), (
        f"expected HEAD in watched files, got {watched_files}"
    )
    assert any(
        dir_.endswith("refs/heads") or dir_.endswith("refs\\heads") for dir_ in watched_dirs
    ), f"expected refs/heads in watched dirs, got {watched_dirs}"


def test_rewriting_head_triggers_reload_after_debounce(qtbot, repo_path):
    """Overwriting .git/HEAD content should fire the debounced reload."""
    calls: list[None] = []
    d = RepoChangeDetector(str(repo_path), on_reload=lambda: calls.append(None))

    head_path = repo_path / ".git" / "HEAD"
    # On macOS, QFileSystemWatcher.fileChanged can take ~500 ms to arrive
    # (kqueue/FSEvents latency in a QApplication context).  Use waitSignal so
    # we block until the OS event is actually delivered rather than relying on
    # a fixed sleep that may be shorter than the platform latency.
    with qtbot.waitSignal(d._watcher.fileChanged, timeout=2000):
        head_path.write_text("ref: refs/heads/other\n", encoding="utf-8")

    qtbot.wait(300)  # let the 200 ms debounce fire
    assert len(calls) >= 1, "reload callback should fire after .git/HEAD is rewritten"


def test_missing_git_dir_does_not_crash(qtbot, tmp_path):
    """Constructing against a non-git directory should log a warning but
    not raise."""
    calls: list[None] = []
    d = RepoChangeDetector(str(tmp_path), on_reload=lambda: calls.append(None))

    # Empty watch set — nothing to watch.
    assert d._watcher.files() == []
    assert d._watcher.directories() == []


def test_stop_releases_all_watches(qtbot, repo_path):
    calls: list[None] = []
    d = RepoChangeDetector(str(repo_path), on_reload=lambda: calls.append(None))

    assert len(d._watcher.files()) + len(d._watcher.directories()) > 0

    d.stop()

    assert d._watcher.files() == []
    assert d._watcher.directories() == []


def test_stop_on_empty_watcher_does_not_warn(qtbot, tmp_path):
    """When stop() runs on a detector whose watch list never populated (e.g.
    a monorepo subdirectory with no .git/ of its own), Qt must not emit
    'QFileSystemWatcher::removePaths: list is empty'.

    Captured via qInstallMessageHandler because Qt warnings on Windows do
    not necessarily reach Python's stderr."""
    messages: list[str] = []

    def handler(_mode, _ctx, msg):
        messages.append(msg)

    old_handler = qInstallMessageHandler(handler)
    try:
        d = RepoChangeDetector(str(tmp_path), on_reload=lambda: None)
        assert d._watcher.files() == []
        assert d._watcher.directories() == []
        d.stop()
    finally:
        qInstallMessageHandler(old_handler)

    assert not any("list is empty" in m for m in messages), (
        f"Qt should not warn on empty removePaths; messages were: {messages!r}"
    )
