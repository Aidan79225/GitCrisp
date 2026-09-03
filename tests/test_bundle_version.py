"""The macOS bundle has to be stamped with the version that actually shipped.

`CFBundleShortVersionString` was the literal "0.1.0" for twenty-six releases:
every .app since v0.1.0 told Finder's Get Info, and the About box, that it was
v0.1.0 — whatever tag had built it. Nothing caught it because the spec is a
build file that no test ever looked at.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC = REPO_ROOT / "GitCrisp.spec"


def _bundle_version(monkeypatch, baked: str | None) -> str:
    """Run the spec's version helper the way PyInstaller would.

    The spec is executed rather than imported: it is a build file, and its
    header is the only part that has to be evaluated to reach the helper.
    """
    if baked is None:
        monkeypatch.setattr(
            "git_gui.observability._get_baked_config", lambda: (None, None), raising=True
        )
    else:
        monkeypatch.setattr(
            "git_gui.observability._get_baked_config", lambda: (None, baked), raising=True
        )
    monkeypatch.delenv("GITCRISP_VERSION", raising=False)

    source = SPEC.read_text()
    header = source[: source.index("a = Analysis(")]
    namespace: dict = {"SPECPATH": str(REPO_ROOT)}
    exec(compile(header, str(SPEC), "exec"), namespace)  # our own build file
    return namespace["_bundle_version"]()


@pytest.mark.parametrize("tag_version", ["0.26.0", "1.0.0", "1.2.3"])
def test_the_bundle_carries_the_version_the_release_baked(monkeypatch, tag_version):
    assert _bundle_version(monkeypatch, tag_version) == tag_version


def test_a_local_build_is_not_stamped_as_a_release(monkeypatch):
    """No baked version resolves to "unknown", which no plist will accept."""
    assert _bundle_version(monkeypatch, None) == "0.0.0"


def test_the_spec_carries_no_version_literal():
    """The literal is what rotted. A number here again should fail loudly."""
    source = SPEC.read_text()
    plist = source[source.index("info_plist=") :]

    for key in ("CFBundleShortVersionString", "CFBundleVersion"):
        assert f"{key}': _bundle_version()" in plist, f"{key} must not be a literal"


def test_pyproject_does_not_claim_to_be_a_release():
    """It reaches the app through importlib.metadata when the checkout is
    installed, and a stale number there would report a version that shipped."""
    import tomllib

    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())

    assert data["project"]["version"] == "0.0.0"
