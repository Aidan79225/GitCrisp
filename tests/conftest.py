import pytest
import pygit2
from pathlib import Path


@pytest.fixture(autouse=True, scope="session")
def _theme_manager():
    """Initialize ThemeManager singleton for tests that touch theme-aware code."""
    from PySide6.QtWidgets import QApplication
    from git_gui.presentation.theme import ThemeManager, set_theme_manager
    app = QApplication.instance() or QApplication([])
    try:
        set_theme_manager(ThemeManager(app))
    except Exception:
        # Builtin theme JSON may be temporarily out of sync with Colors
        # during multi-step refactors; tests that need the manager will
        # fail individually.
        pass
    yield


@pytest.fixture
def repo_path(tmp_path) -> Path:
    """Creates a temp git repo with one commit on 'master'."""
    repo = pygit2.init_repository(str(tmp_path))
    repo.config["user.name"] = "Test User"
    repo.config["user.email"] = "test@example.com"
    sig = pygit2.Signature("Test User", "test@example.com")
    (tmp_path / "README.md").write_text("# Test Repo\n")
    repo.index.add("README.md")
    repo.index.write()
    tree = repo.index.write_tree()
    repo.create_commit("refs/heads/master", sig, sig, "Initial commit", tree, [])
    return tmp_path


@pytest.fixture
def repo_impl(repo_path):
    from git_gui.infrastructure.pygit2_repo import Pygit2Repository
    return Pygit2Repository(str(repo_path))
