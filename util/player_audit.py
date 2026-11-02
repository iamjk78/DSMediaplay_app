"""
The check of what a player has after a deploy, against what the server says it was sent.

The player is asked once by a fixed command (`PLAYER_AUDIT_COMMAND`) that only reads: it lists its files with their
sizes and, of the files that hold settings, prints a short digest of each part instead of the part itself (a group has
dozens of playlists, and their contents would be a lot to send for every player). The same digests are worked out here
from what the server has, and what differs is named. This module holds the logic with no network in it.
"""
import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple

MEDIA_DIR = "/home/pi/media"
CONFIG_DIR = "/home/pi/piSignagePro/config"

# The parts of a playlist file that are compared (its labels, groups and version do not matter for what is played)
PLAYLIST_PARTS = ("layout", "settings", "templateName", "schedule", "videoWindow", "zoneVideoWindow")

# The settings of a group that the player keeps in _settings.json (a key that one side lacks is not compared)
GROUP_SETTING_KEYS = (
    "alternateContent", "animationEnable", "animationType", "combineDefaultPlaylist", "disableAp", "disableWarnings",
    "disableWebUi", "emergencyMessage", "enableMpv", "enablePio", "imageLetterboxed", "keepWeblinksInMemory", "kioskUi",
    "loadPlaylistOnCompletion", "logo", "logox", "logoy", "mpvAudioDelay", "omxVolume", "orientation",
    "playAllEligiblePlaylists", "reboot", "resizeAssets", "resolution", "showClock", "shuffleContent",
    "signageBackgroundColor", "timeToStopVideo", "urlReloadDisable", "videoKeepAspect", "videoShowSubtitles",
)


def digest(value: Any) -> str:
    """A short digest of a value; the player works it out the same way (see the script below)."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def playlist_digests(playlist: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """The digests of the parts of a playlist (its file on the player is made of the same object)."""
    if not isinstance(playlist, dict):
        return None
    rows = playlist.get("assets") or []
    parts = {part: digest(playlist.get(part)) for part in PLAYLIST_PARTS}
    parts["order"] = digest([row.get("filename") for row in rows if isinstance(row, dict)])
    parts["rows"] = digest(rows)
    return parts


# Runs on the player (Python 3.7 there): reads, and prints one line of JSON. The folders and the lists are filled in
# by `_script()`; nothing that comes from outside is ever put into it.
_SCRIPT = r'''
import hashlib, json, os
def digest(value):
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
def load(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None
MEDIA, CONFIG, PARTS, KEYS = @MEDIA@, @CONFIG@, @PARTS@, @KEYS@
files, playlists = {}, {}
for name in os.listdir(MEDIA):
    path = os.path.join(MEDIA, name)
    if not os.path.isfile(path):
        continue
    files[name] = os.path.getsize(path)
    if name.startswith("__") and name.endswith(".json"):
        data = load(path)
        if isinstance(data, dict):
            rows = data.get("assets") or []
            entry = {part: digest(data.get(part)) for part in PARTS}
            entry["order"] = digest([row.get("filename") for row in rows if isinstance(row, dict)])
            entry["rows"] = digest(rows)
            playlists[name[2:-5]] = entry
        else:
            playlists[name[2:-5]] = None
settings = load(os.path.join(CONFIG, "_settings.json")) or {}
config = load(os.path.join(CONFIG, "_config.json")) or {}
print(json.dumps({"files": files, "playlists": playlists,
                  "deployed": digest(config.get("deployedPlaylists") or []),
                  "validity": digest(settings.get("assetsValidity") or []),
                  "settings": {key: digest(settings[key]) for key in KEYS if key in settings}}, sort_keys=True))
'''


def script(media: str = MEDIA_DIR, config: str = CONFIG_DIR) -> str:
    """The script with its constants; the folders are parameters only so that a test can point them at a temp folder."""
    return (_SCRIPT.replace("@MEDIA@", json.dumps(media)).replace("@CONFIG@", json.dumps(config))
            .replace("@PARTS@", json.dumps(list(PLAYLIST_PARTS))).replace("@KEYS@", json.dumps(list(GROUP_SETTING_KEYS))))


PLAYER_AUDIT_COMMAND = "python3 - <<'PY'\n" + script() + "PY\n"


def parse_size(text: Any) -> Optional[Tuple[int, int]]:
    """
    The size the server writes ("351839B", "7401KB", "12.3MB") as bytes and how far from it the real size may be: bytes
    are exact, bigger units are rounded, so a size matches within one unit of the last digit the server wrote.
    """
    found = re.fullmatch(r"\s*(\d+(?:\.(\d+))?)\s*(B|KB|MB|GB)\s*", str(text), flags=re.IGNORECASE)
    if not found:
        return None
    unit = {"B": 1, "KB": 1000, "MB": 1000 ** 2, "GB": 1000 ** 3}[found.group(3).upper()]
    decimals = len(found.group(2) or "")
    return round(float(found.group(1)) * unit), 0 if unit == 1 else round(unit / 10 ** decimals)


def expected_audit(group: Dict[str, Any], playlists: Dict[str, Dict[str, Any]], files: List[str],
                   sizes: Dict[str, Tuple[int, int]]) -> Dict[str, Any]:
    """
    What a player of `group` should have: the `files` (what the group sends, see ServerApi.get_group_files) with the
    `sizes` the server knows, the digests of the deployed playlists, the validity of the assets, the settings of the group
    and of each playlist file; and what the group has changed since the last deploy.
    """
    deployed_entries = group["deployedPlaylists"] if group.get("deployedPlaylists") is not None else group.get("playlists")
    undeployed = []
    if group.get("deployedPlaylists") is not None and group.get("playlists") != group["deployedPlaylists"]:
        undeployed.append("playlists")
    if group.get("deployedAssets") is not None and group.get("assets") != group["deployedAssets"]:
        undeployed.append("assets")
    return {
        "group": group.get("name", ""),
        "files": files,
        "sizes": {name: sizes[name] for name in files if name in sizes},
        "deployed": digest(deployed_entries or []),
        "validity": digest(group.get("assetsValidity") or []),
        "settings": {key: digest(group[key]) for key in GROUP_SETTING_KEYS if key in group},
        "playlists": {name[2:-5]: playlist_digests(playlists.get(name[2:-5])) for name in files
                      if name.startswith("__") and name.endswith(".json") and name[2:-5] in playlists},
        "undeployed": undeployed,
    }


def compare_audit(expected: Dict[str, Any], actual: Dict[str, Any]) -> Dict[str, Any]:
    """
    What the player lacks or has otherwise than expected. Only what the player reported is judged (a player that could
    not tell its settings still tells its files). The differing parts of a playlist are named by their key in
    PLAYLIST_PARTS, "order" (the assets or their order) or "rows" (the settings of the assets), or "corrupt" for a file
    that cannot be read; when the order differs the rows differ with it, so only the order is named.
    """
    on_player: Dict[str, Optional[int]] = actual.get("files") or {}
    missing = [name for name in expected["files"] if name not in on_player]
    wrong_size = []
    for name, (size, tolerance) in expected["sizes"].items():
        have = on_player.get(name)
        if have is not None and abs(have - size) > tolerance:
            wrong_size.append((name, size, have))
    different: Dict[str, Any] = {
        "deployed": "deployed" in actual and actual["deployed"] != expected["deployed"],
        "validity": "validity" in actual and actual["validity"] != expected["validity"],
        "settings": sorted(key for key, value in expected["settings"].items()
                           if key in (actual.get("settings") or {}) and actual["settings"][key] != value),
        "playlists": {},
    }
    for name, parts in expected["playlists"].items():
        if name not in (actual.get("playlists") or {}) or parts is None:
            continue
        have = actual["playlists"][name]
        if have is None:
            different["playlists"][name] = ["corrupt"]
            continue
        names = [part for part in (*PLAYLIST_PARTS, "order", "rows") if have.get(part) != parts.get(part)]
        if "order" in names and "rows" in names:
            names.remove("rows")
        if names:
            different["playlists"][name] = names
    return {"missing": missing, "wrong_size": wrong_size, "different": different}


def has_differences(result: Dict[str, Any]) -> bool:
    different = result["different"]
    return bool(result["missing"] or result["wrong_size"] or different["deployed"] or different["validity"]
                or different["settings"] or different["playlists"])
