from pathlib import Path

import pygit2
import pytest


@pytest.fixture(autouse=True, scope="session")
def _isolated_settings(tmp_path_factory):
    """Keep the suite out of the developer's real config.

    MainWindow persists its window geometry and splitter arrangement on close,
    and pytest-qt closes every widget it adopts — so without this, running the
    tests would silently overwrite the layout of the app the developer is
    using.
    """
    from PySide6.QtCore import QCoreApplication, QSettings

    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(
        QSettings.IniFormat, QSettings.UserScope, str(tmp_path_factory.mktemp("qsettings"))
    )
    QCoreApplication.setOrganizationName("GitCrispTest")
    QCoreApplication.setApplicationName("GitCrispTest")
    yield


@pytest.fixture(autouse=True, scope="session")
def _theme_manager():
    """Initialize ThemeManager singleton for tests that touch theme-aware code."""
    from PySide6.QtWidgets import QApplication

    from git_gui.presentation.theme import ThemeManager, set_theme_manager

    app = QApplication.instance() or QApplication([])
    set_theme_manager(ThemeManager(app))
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
    from git_gui.infrastructure.pygit2 import Pygit2Repository

    return Pygit2Repository(str(repo_path))
