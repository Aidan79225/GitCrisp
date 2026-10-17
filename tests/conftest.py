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
def _isolated_theme_settings(_isolated_gitcrisp_home):
    """Keep the theme's settings.json out of the developer's AppData.

    ``settings_path()`` comes from ``QStandardPaths.AppDataLocation``, which
    neither the QSettings redirect nor ``Path.home()`` reaches. Every
    ``set_mode`` in the suite wrote there and the session's ThemeManager read
    it back at startup, so one run's theme mode and typography scale became
    the next run's starting state, on every checkout of the machine.
    """
    from git_gui.presentation.theme import settings

    path = _isolated_gitcrisp_home / "AppData" / "GitStack" / "settings.json"
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(settings, "settings_path", lambda: path)
        yield path


@pytest.fixture(autouse=True, scope="session")
def _theme_manager(_isolated_theme_settings):
    """Initialize ThemeManager singleton for tests that touch theme-aware code."""
    from PySide6.QtWidgets import QApplication

    from git_gui.presentation.theme import ThemeManager, set_theme_manager

    app = QApplication.instance() or QApplication([])
    set_theme_manager(ThemeManager(app))
    yield


@pytest.fixture
def repo_path(tmp_path) -> Path:
    """Creates a temp git repo with one commit on 'master'."""
    repo = pygit2.init_repository(str(tmp_path), initial_head="master")
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


@pytest.fixture(autouse=True)
def _reset_crash_reporting_state(monkeypatch):
    """Keep one test's crash-reporting preference from leaking into the next.

    ``git_gui.observability`` holds whether reporting is on in module
    globals, and a test that turns it off (directly, or by accepting the
    Preferences dialog) would otherwise make every later ``before_send``
    test see events dropped.
    """
    import git_gui.observability as obs

    monkeypatch.setattr(obs, "_enabled", True)
    monkeypatch.setattr(obs, "_initialized", False)


@pytest.fixture(autouse=True)
def _no_sentry_dsn(monkeypatch):
    """Keep every test away from a real Sentry project.

    The release workflow bakes the production DSN into ``_build_config``
    before it runs the suite, so a test that turns crash reporting on —
    accepting the Preferences dialog does — started the real client, and
    the tests that log CRITICAL or raise on purpose then reported to
    production as the release being built. The baked version is kept: the
    About box and the update check read it. A test that needs a DSN sets one.
    """
    import git_gui.observability as obs

    baked_config = obs._get_baked_config
    monkeypatch.setattr(obs, "_get_baked_config", lambda: (None, baked_config()[1]))
    monkeypatch.delenv("GITCRISP_SENTRY_DSN", raising=False)
