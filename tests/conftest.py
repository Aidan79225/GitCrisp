from pathlib import Path

import pygit2
import pytest
from pygit2.enums import ConfigLevel


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
def _isolated_check_icon_dir(_isolated_gitcrisp_home):
    """Keep the tinted checkbox ticks out of the developer's real cache.

    ``_icon_dir()`` comes from ``QStandardPaths.CacheLocation``, which Qt
    resolves itself, past the ``Path.home()`` redirect, and every
    ThemeManager renders the stylesheet at startup. Yields the real
    ``_icon_dir`` so a test can check where it points without writing there.
    """
    from git_gui.presentation.theme import qss_template

    real_icon_dir = qss_template._icon_dir
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(qss_template, "_icon_dir", lambda: _isolated_gitcrisp_home / "cache")
        yield real_icon_dir


@pytest.fixture(autouse=True, scope="session")
def _theme_manager(_isolated_theme_settings, _isolated_check_icon_dir):
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


@pytest.fixture
def global_default_branch_main(tmp_path_factory):
    """A global git config naming ``main`` as the default branch.

    The suite leaves HOME alone, so libgit2 reads the contributor's own
    global config; a fixture repo must land on the branch its tests name
    whatever ``init.defaultBranch`` says there.
    """
    config_dir = tmp_path_factory.mktemp("global-git-config")
    (config_dir / ".gitconfig").write_text("[init]\n\tdefaultBranch = main\n", encoding="utf-8")
    search_path = pygit2.settings.search_path
    original = search_path[ConfigLevel.GLOBAL]
    search_path[ConfigLevel.GLOBAL] = str(config_dir)
    try:
        yield
    finally:
        search_path[ConfigLevel.GLOBAL] = original


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


@pytest.fixture(autouse=True)
def _no_update_check(monkeypatch):
    """Keep every window from asking GitHub for the latest release.

    With the release tag baked in, ``MainWindow.__init__`` starts the update
    check, so each window a test built sent an unauthenticated request to the
    releases API from every release runner. Only the request is cut: the
    preference and the version stay real for the tests that read them. The
    checker's own tests override this fixture.
    """
    from git_gui.presentation.services.update_checker import UpdateChecker

    monkeypatch.setattr(UpdateChecker, "check", lambda self: None)
