import os
import sys
from pathlib import Path
from typing import Optional

from platformdirs import user_config_path, user_downloads_path, user_log_path

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


def downloads_dir() -> Path:
    """The Downloads folder of the current user; the home folder if there is none (or it has been removed)."""
    folder = user_downloads_path()
    return folder if folder.is_dir() else Path.home()


def legacy_login_file() -> Optional[Path]:
    """
    Where the old, network-drive-launched version of the app kept its accounts (Windows only, `%APPDATA%` is not
    set anywhere else): read once, to offer a one-time import from it. Nothing of this app ever writes here.
    """
    appdata = os.environ.get("APPDATA")
    return Path(appdata) / "dsmediaplay" / "login.json" if appdata else None
