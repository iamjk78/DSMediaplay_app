"""
Looking for a newer version of the application in the releases of its GitHub repository, and installing it.

Nothing here touches Tk: the window calls these functions from a worker thread and shows what they say. A failure is an
UpdateError whose `key` is the messages.json key of the text to show.

What is trusted, since the builds are not signed: the address of the repository below and TLS. A file is installed
only when it comes from a release of that repository and its SHA-256 equals the one GitHub reports for the asset
(`digest`); a release without that is offered for download in the browser only.
"""
import hashlib
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from util.version import VERSION

REPOSITORY = "iamjk78/DSMediaplay_app"
RELEASES_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASE_PAGES = f"https://github.com/{REPOSITORY}/"
DOWNLOAD_PREFIX = f"https://github.com/{REPOSITORY}/releases/download/"
REQUEST_TIMEOUT = 15  # seconds, for one request and for a stall of the download
CHUNK = 64 * 1024
UPDATE_FOLDER = "DSMediaplay_app-update"
BUNDLE_NAME = "DSMediaplay_app.app"
BUNDLE_IDENTIFIER = "media.bluetouch.dsm-gui"  # what the macOS build is made with (DSMediaplay_app.spec)
# The names the Build workflow gives the files of a release
WINDOWS_ASSET = re.compile(r"DSMediaplay_app-Setup-[0-9]+(\.[0-9]+)*\.exe")
MACOS_ASSET = re.compile(r"DSMediaplay_app-macos\.zip")
# Where a download may be redirected to: GitHub's own hosts
TRUSTED_HOSTS = ("github.com", "githubusercontent.com")

# Waits until the application that started it has ended, then puts the new bundle in place of the old one (the old one
# is kept until the new one is there, and put back when it cannot be) and starts it. The paths are arguments, never
# part of the script, so no name of a folder can become a command.
MACOS_SWAP_SCRIPT = """#!/bin/sh
pid="$1"; new="$2"; target="$3"; opener="$4"; staging="$5"
mkdir -p "$HOME/Library/Logs"
exec >> "$HOME/Library/Logs/DSMediaplay_app-update.log" 2>&1
echo "$(date '+%Y-%m-%d %H:%M:%S') updating $target from $new"
waited=0
while kill -0 "$pid" 2>/dev/null; do
  sleep 0.5
  waited=$((waited + 1))
  if [ "$waited" -gt 120 ]; then echo "the application did not end, nothing changed"; rm -rf "$staging"; exit 1; fi
done
old="$target.replaced-$$"
if mv "$target" "$old" && mv "$new" "$target"; then
  rm -rf "$old" "$staging"
  echo "done"
else
  echo "could not replace, putting the old one back"
  if [ ! -e "$target" ] && [ -e "$old" ]; then mv "$old" "$target"; fi
  rm -rf "$staging"
  "$opener" "$target"
  exit 1
fi
"$opener" "$target"
"""


class UpdateError(Exception):
    """Something that stops an update; `key` is the messages.json key of the text, `values` fill its {names}."""

    def __init__(self, key: str, **values: str) -> None:
        super().__init__(key)
        self.key = key
        self.values = values


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int
    sha256: str  # "" when GitHub did not report one


@dataclass(frozen=True)
class Release:
    version: str
    page: str  # the page of the release, where it can be downloaded by hand
    asset: Optional[Asset]  # the file of this platform, None when the release has none


def parse_version(text: str) -> Tuple[int, ...]:
    """(1, 0, 9) for "1.0.9" or "v1.0.9"; ValueError for anything that is not numbers separated by dots."""
    parts = text.strip().lstrip("vV").split(".")
    if not parts or not all(part.isdigit() for part in parts):
        raise ValueError(f"not a version: {text!r}")
    return tuple(int(part) for part in parts)


def is_newer(candidate: str, current: str = VERSION) -> bool:
    """Whether `candidate` is a later version than `current` (1.0 and 1.0.0 are the same)."""
    def padded(version: Tuple[int, ...]) -> Tuple[int, ...]:
        return version + (0,) * (3 - len(version))
    return padded(parse_version(candidate)) > padded(parse_version(current))


def _asset_for(assets: List[dict], platform: str) -> Optional[Asset]:
    pattern = WINDOWS_ASSET if platform == "win32" else MACOS_ASSET if platform == "darwin" else None
    for item in assets:
        name, url = item.get("name"), item.get("browser_download_url")
        if not (pattern and isinstance(name, str) and isinstance(url, str) and pattern.fullmatch(name)):
            continue
        if not re.fullmatch(re.escape(DOWNLOAD_PREFIX) + r"[A-Za-z0-9][A-Za-z0-9._-]*/" + re.escape(name), url) \
                or ".." in url:  # exactly where the release of this repository keeps the file, nowhere else
            continue
        size = item.get("size")
        digest = item.get("digest")
        found = re.fullmatch(r"sha256:([0-9a-f]{64})", digest) if isinstance(digest, str) else None
        return Asset(name, url, size if isinstance(size, int) else 0, found.group(1) if found else "")
    return None


def fetch_latest_release(platform: str = sys.platform) -> Optional[Release]:
    """
    The latest published release (not a draft, not a pre-release), None when the repository has none yet. The file
    of `platform` is in it when the release has one.
    """
    try:
        response = requests.get(RELEASES_API, timeout=REQUEST_TIMEOUT, headers=_headers())
    except requests.RequestException:
        raise UpdateError("update_check_failed")
    if response.status_code == 404:
        return None
    if response.status_code in (403, 429):
        raise UpdateError("update_rate_limited")
    if not response.ok:
        raise UpdateError("update_check_failed")
    try:
        data = response.json()
        tag, page, assets = data["tag_name"], data["html_url"], data.get("assets", [])
        if data.get("draft") or data.get("prerelease"):
            return None
        parse_version(tag)
        if not (isinstance(page, str) and page.startswith(RELEASE_PAGES) and isinstance(assets, list)):
            raise ValueError("unexpected answer")
    except (ValueError, KeyError, TypeError, AttributeError):
        raise UpdateError("update_check_failed")
    return Release(tag.lstrip("vV"), page, _asset_for([item for item in assets if isinstance(item, dict)], platform))


def _headers() -> dict:
    return {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"DSMediaplay_app/{VERSION}"}


def running_bundle() -> Optional[Path]:
    """The .app the running application is in; None when it is not run from a macOS bundle."""
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return None
    bundle = Path(sys.executable).resolve().parents[2]
    return bundle if bundle.suffix == ".app" else None


def check_installable(release: Release, platform: str = sys.platform) -> Asset:
    """
    The file to install, or an UpdateError that says why this release cannot be installed from the application (it
    can still be downloaded by hand from its page).
    """
    if not getattr(sys, "frozen", False):
        raise UpdateError("update_not_installed_app")
    if platform not in ("win32", "darwin"):
        raise UpdateError("update_unsupported_platform")
    if release.asset is None:
        raise UpdateError("update_no_asset")
    if not release.asset.sha256:
        raise UpdateError("update_no_checksum")
    if platform == "darwin":
        bundle = running_bundle()
        if bundle is None or not os.access(bundle.parent, os.W_OK):
            raise UpdateError("update_not_writable", folder=str(bundle.parent) if bundle else "")
    return release.asset


def update_directory() -> Path:
    return Path(tempfile.gettempdir()) / UPDATE_FOLDER


def download(asset: Asset, directory: Path, progress: Optional[Callable[[int, int], None]] = None,
             cancelled: Optional[Callable[[], bool]] = None) -> Path:
    """
    Downloads the asset into `directory` and checks it against the size and the SHA-256 GitHub reports; the file gets
    its name only when it is whole and right. `progress(received, total)` is told as it goes; `cancelled()` is asked
    for every part. Raises UpdateError otherwise, leaving nothing behind.
    """
    if not asset.sha256:
        raise UpdateError("update_no_checksum")
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True)
    target = directory / asset.name
    partial = directory / (asset.name + ".part")
    digest, received = hashlib.sha256(), 0
    try:
        with requests.get(asset.url, stream=True, timeout=REQUEST_TIMEOUT, headers=_headers()) as response:
            response.raise_for_status()
            host = urlparse(response.url).hostname or ""
            if urlparse(response.url).scheme != "https" or not any(
                    host == trusted or host.endswith("." + trusted) for trusted in TRUSTED_HOSTS):
                raise UpdateError("update_download_failed")
            with open(partial, "wb") as file:
                for chunk in response.iter_content(CHUNK):
                    if cancelled and cancelled():
                        raise UpdateError("update_cancelled")
                    file.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
                    if progress:
                        progress(received, asset.size)
        if received != asset.size or digest.hexdigest() != asset.sha256:
            raise UpdateError("update_checksum_mismatch")
        os.replace(partial, target)
    except UpdateError:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    except (requests.RequestException, OSError):
        shutil.rmtree(directory, ignore_errors=True)
        raise UpdateError("update_download_failed")
    return target


def launch_windows_installer(installer: Path) -> None:
    """
    Starts the installer on its own, so that it goes on when the application ends (it stops the application itself if it
    still runs, replaces its files and, with /RELAUNCH=1, starts the new one).
    """
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        subprocess.Popen([str(installer), "/SILENT", "/NORESTART", "/CLOSEAPPLICATIONS", "/RELAUNCH=1"], close_fds=True,
                         creationflags=flags, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except OSError:  # the file is gone (a virus scanner took it) or cannot be run
        raise UpdateError("update_invalid_package")


def stage_macos_update(package: Path, version: str, bundle: Path, opener: str = "open",
                       pid: Optional[int] = None) -> None:
    """
    Unpacks the downloaded zip next to the installed bundle (the same volume, so that the swap is a rename), checks that
    it is this application in the version that was announced, and starts the script that swaps the two once this
    process (`pid`) has ended. The caller ends the application right after.
    """
    staging = Path(tempfile.mkdtemp(prefix=".DSMediaplay_app-update-", dir=bundle.parent))
    try:
        subprocess.run(["ditto", "-x", "-k", str(package), str(staging)], check=True, capture_output=True, timeout=300)
        new = staging / BUNDLE_NAME
        with open(new / "Contents" / "Info.plist", "rb") as file:
            info = plistlib.load(file)
        if (info.get("CFBundleIdentifier") != BUNDLE_IDENTIFIER
                or info.get("CFBundleShortVersionString") != version
                or not (new / "Contents" / "MacOS" / info.get("CFBundleExecutable", "")).is_file()):
            raise UpdateError("update_invalid_package")
        script = staging / "swap.sh"
        script.write_text(MACOS_SWAP_SCRIPT, encoding="utf-8")
        script.chmod(0o700)
        subprocess.Popen(["/bin/sh", str(script), str(os.getpid() if pid is None else pid), str(new), str(bundle), opener, str(staging)],
                         start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except UpdateError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except (OSError, subprocess.SubprocessError, plistlib.InvalidFileException, KeyError, ValueError):
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError("update_invalid_package")


def install(package: Path, release: Release, platform: str = sys.platform) -> None:
    """Hands the downloaded file over to what installs it; the application has to end afterwards."""
    if platform == "win32":
        launch_windows_installer(package)
    elif platform == "darwin":
        bundle = running_bundle()
        if bundle is None:
            raise UpdateError("update_not_installed_app")
        stage_macos_update(package, release.version, bundle)
    else:
        raise UpdateError("update_unsupported_platform")
