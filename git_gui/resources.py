import sys
from pathlib import Path

# Project root when running from source
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_resource_path(relative: str) -> Path:
    """Resolve a path relative to the project root or PyInstaller bundle."""
    if getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS) / relative
    return _PROJECT_ROOT / relative
