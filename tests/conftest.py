from pathlib import Path

import pygit2
import pytest


@pytest.fixture(autouse=True, scope="session")
def _isolated_gitcrisp_home(tmp_path_factory):
    """Keep the suite out of the developer's real ``~/.gitcrisp``.

    ``JsonRepoStore``, ``JsonRemoteTagCache`` and the avatar cache all default
    to a path under ``Path.home()``, and a handful of tests construct them with
    no argument to get that default. Those stores are then *saved* — by a repo
    switch, or by MainWindow's own teardown — so running the suite overwrote
    the developer's open/recent repo list with whatever the test had, which is
    nothing. Recovering it afterwards means guessing at paths from cache
    filenames, so the fix belongs here: nothing the suite does may land in the
    real home.

    Only ``Path.home()`` is redirected, not ``HOME``/``USERPROFILE``: the
    subprocess ``git`` calls in the suite still need the real environment to
    find a usable git config.
    """
    fake_home = tmp_path_factory.mktemp("home")
    (fake_home / ".gitcrisp").mkdir()
    original = Path.home
    Path.home = classmethod(lambda cls: fake_home)  # type: ignore[method-assign]
    try:
        yield fake_home
    finally:
        Path.home = original  # type: ignore[method-assign]


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
