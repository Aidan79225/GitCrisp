import subprocess
import sys
from pathlib import Path

# Project root when running from source
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_resource_path(relative: str) -> Path:
    """Resolve a path relative to the project root or PyInstaller bundle."""
    if getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS) / relative
    return _PROJECT_ROOT / relative


def subprocess_kwargs() -> dict:
    """Extra kwargs for subprocess calls to suppress console windows on Windows."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}
