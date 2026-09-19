import sys
from pathlib import Path

from platformdirs import user_config_path, user_log_path

APP_NAME = "DSM_GUI"
DEFAULT_LOGINS_FILE = "logins.json"


def resource_path(relative: str) -> Path:
    """Resolves a bundled read-only resource both from source and from a PyInstaller build."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative


def default_logins_file() -> Path:
    """Per-user, writable location of the account list (never inside the app folder or the repository)."""
    directory = user_config_path(APP_NAME, appauthor=False, ensure_exists=True)
    return directory / DEFAULT_LOGINS_FILE


def log_dir() -> Path:
    return user_log_path(APP_NAME, appauthor=False, ensure_exists=True)
