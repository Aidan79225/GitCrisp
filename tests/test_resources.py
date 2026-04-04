import sys
from pathlib import Path
from git_gui.resources import get_resource_path


def test_get_resource_path_normal():
    """In normal (non-frozen) mode, resolves relative to project root."""
    result = get_resource_path("arts")
    assert result.name == "arts"
    assert result.parent == Path(__file__).resolve().parent.parent


def test_get_resource_path_frozen(monkeypatch):
    """In PyInstaller frozen mode, resolves relative to _MEIPASS."""
    fake_meipass = "/tmp/fake_meipass"
    monkeypatch.setattr(sys, "_MEIPASS", fake_meipass, raising=False)
    result = get_resource_path("arts")
    assert result == Path(fake_meipass) / "arts"
