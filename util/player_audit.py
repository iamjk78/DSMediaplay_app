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


def strip_nulls(value: Any) -> Any:
    """A value without the keys that hold null: the player writes `"time": null` where the server has no key at all."""
    if isinstance(value, dict):
        return {key: strip_nulls(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [strip_nulls(item) for item in value]
    return value


def digest(value: Any) -> str:
    """A short digest of a value; the player works it out the same way (see the script below)."""
    text = json.dumps(strip_nulls(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def normalize_deployed(entries: Any) -> List[Any]:
    """
    The playlists of a group as the player keeps them: an entry without `settings` (TV_OFF) has an empty one there. The
    script on the player does the same, so that this is not taken for a difference.
    """
    return [dict(entry, settings=entry.get("settings") or {}) if isinstance(entry, dict) else entry
            for entry in entries or []]


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
def strip_nulls(value):
    if isinstance(value, dict):
        return {key: strip_nulls(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [strip_nulls(item) for item in value]
    return value
def digest(value):
    text = json.dumps(strip_nulls(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
def load(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None
def normalize(entries):
    return [dict(e, settings=e.get("settings") or {}) if isinstance(e, dict) else e for e in entries or []]
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
                  "deployed": digest(normalize(config.get("deployedPlaylists"))),
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
        "deployed": digest(normalize_deployed(deployed_entries)),
        "validity": digest(group.get("assetsValidity") or []),
        "settings": {key: digest(group[key]) for key in GROUP_SETTING_KEYS if key in group},
        "playlists": {name[2:-5]: playlist_digests(playlists.get(name[2:-5])) for name in files
                      if name.startswith("__") and name.endswith(".json") and name[2:-5] in playlists},
        "undeployed": undeployed,
        "values": {"deployed": normalize_deployed(deployed_entries),
                   "validity": group.get("assetsValidity") or [],
                   "settings": {key: group[key] for key in GROUP_SETTING_KEYS if key in group},
                   "playlists": {name[2:-5]: playlists[name[2:-5]] for name in files
                                 if name.startswith("__") and name.endswith(".json") and name[2:-5] in playlists}},
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


# ---- what exactly differs: the values from the server and from the player, side by side

MISSING = "<není>"

_DETAIL_SCRIPT = r'''
import json, os
def load(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None
def normalize(entries):
    return [dict(e, settings=e.get("settings") or {}) if isinstance(e, dict) else e for e in entries or []]
MEDIA, CONFIG, WANT = @MEDIA@, @CONFIG@, json.loads(@WANT@)
settings = load(os.path.join(CONFIG, "_settings.json")) or {}
config = load(os.path.join(CONFIG, "_config.json")) or {}
out = {}
if WANT.get("deployed"):
    out["deployed"] = normalize(config.get("deployedPlaylists"))
if WANT.get("validity"):
    out["validity"] = settings.get("assetsValidity") or []
out["settings"] = {key: settings[key] for key in WANT.get("settings", []) if key in settings}
out["playlists"] = {}
for name, parts in WANT.get("playlists", {}).items():
    data = load(os.path.join(MEDIA, "__" + name + ".json"))
    if not isinstance(data, dict):
        out["playlists"][name] = None
        continue
    rows = data.get("assets") or []
    entry = {part: data.get(part) for part in parts if part not in ("order", "rows")}
    if "order" in parts:
        entry["order"] = [row.get("filename") for row in rows if isinstance(row, dict)]
    if "rows" in parts:
        entry["rows"] = rows
    out["playlists"][name] = entry
print(json.dumps(out, sort_keys=True))
'''


def detail_request(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """What to read from the player to say what differs; None when nothing that has a value to show differs."""
    different = result["different"]
    playlists = {name: [part for part in parts if part != "corrupt"] for name, parts in different["playlists"].items()}
    playlists = {name: parts for name, parts in playlists.items() if parts}
    want = {"deployed": different["deployed"], "validity": different["validity"], "settings": different["settings"],
            "playlists": playlists}
    return want if any(want.values()) else None


def detail_script(want: Dict[str, Any], media: str = MEDIA_DIR, config: str = CONFIG_DIR) -> str:
    """
    The script that reads the parts that differ. What is asked for (the names of the playlists come from the server, so
    they can be anything) goes in as one JSON text in a Python string literal; the folders are parameters for the tests.
    """
    return (_DETAIL_SCRIPT.replace("@MEDIA@", json.dumps(media)).replace("@CONFIG@", json.dumps(config))
            .replace("@WANT@", repr(json.dumps(want))))


def detail_command(want: Dict[str, Any]) -> str:
    """The script as a command; the heredoc is quoted, so the shell does not touch a character of it."""
    return "python3 - <<'PY'\n" + detail_script(want) + "PY\n"


def walk(server: Any, player: Any, path: str = ""):
    """
    Where two values differ: (path, the value on the server, the value on the player); MISSING for what one side lacks.
    A key that holds null is a key that is not there.
    """
    if not path:
        server, player = strip_nulls(server), strip_nulls(player)
    if isinstance(server, dict) and isinstance(player, dict):
        for key in sorted(set(server) | set(player), key=str):
            yield from walk(server.get(key, MISSING), player.get(key, MISSING), f"{path}.{key}" if path else str(key))
    elif isinstance(server, list) and isinstance(player, list):
        for index in range(max(len(server), len(player))):
            yield from walk(server[index] if index < len(server) else MISSING,
                            player[index] if index < len(player) else MISSING, f"{path}[{index}]")
    elif server != player:
        yield path, server, player


def walk_keyed(server: List[Any], player: List[Any], key: Optional[str]):
    """
    Where two lists differ, the entries matched by their `key` (and by how many times it has been met, a playlist can be
    in a group twice) and not by their position: one entry more on one side would shift all the others and make every
    one of them differ. The entries only one side has are named first, then the order, then what differs in the others.
    Without a key (a list of names) only the names and the order are told.
    """
    def key_of(item: Any) -> Any:
        return item.get(key) if key and isinstance(item, dict) else item

    def table(items: List[Any]) -> Dict[Tuple[Any, int], Any]:
        met: Dict[Any, int] = {}
        entries = {}
        for item in items:
            name = json.dumps(key_of(item), sort_keys=True)
            entries[(name, met.get(name, 0))] = item
            met[name] = met.get(name, 0) + 1
        return entries

    names_server, names_player = [key_of(item) for item in server], [key_of(item) for item in player]
    only_server = [name for name in names_server if names_server.count(name) > names_player.count(name)]
    only_player = [name for name in names_player if names_player.count(name) > names_server.count(name)]
    if only_server:
        yield "@only_server", list(dict.fromkeys(only_server)), MISSING
    if only_player:
        yield "@only_player", MISSING, list(dict.fromkeys(only_player))
    if not only_server and not only_player and names_server != names_player:
        yield "@order", names_server, names_player
    if key:
        have = table(player)
        for (name, number), item in table(server).items():
            if (name, number) in have:
                label = str(json.loads(name)) + (f"#{number + 1}" if number else "")
                yield from walk(strip_nulls(item), strip_nulls(have[(name, number)]), label)


def short_value(value: Any, limit: int = 80) -> str:
    """A value for a line of the log: as JSON, cut when long; what one side lacks is written as MISSING."""
    text = value if value == MISSING and isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit - 1] + "…"


def part_value(playlist: Dict[str, Any], part: str) -> Any:
    """A part of a playlist as the player reports it in the details."""
    if part == "order":
        return [row.get("filename") for row in playlist.get("assets") or [] if isinstance(row, dict)]
    if part == "rows":
        return playlist.get("assets") or []
    return playlist.get(part)


def _part_places(part: str, server: Any, player: Any):
    if part == "order" and isinstance(player, list):
        return walk_keyed(server, player, None)
    if part == "rows" and isinstance(player, list):
        return walk_keyed(server, player, "filename")
    return walk(server, player)


def differences_in_detail(result: Dict[str, Any], expected: Dict[str, Any], details: Dict[str, Any]) -> Dict[str, Any]:
    """
    For each part that differs the places where the value on the server and on the player are not the same, as
    (path, server, player): {"deployed": [...], "validity": [...], "settings": {key: [...]}, "playlists": {name: {part: [...]}}}.
    """
    values, different = expected["values"], result["different"]
    out: Dict[str, Any] = {"deployed": [], "validity": [], "settings": {}, "playlists": {}}
    if different["deployed"] and "deployed" in details:
        out["deployed"] = list(walk_keyed(values["deployed"], details["deployed"], "name"))
    if different["validity"] and "validity" in details:
        out["validity"] = list(walk_keyed(values["validity"], details["validity"], "name"))
    for key in different["settings"]:
        out["settings"][key] = list(walk(values["settings"].get(key, MISSING), (details.get("settings") or {}).get(key, MISSING)))
    for name, parts in different["playlists"].items():
        have = (details.get("playlists") or {}).get(name)
        if have is None or name not in values["playlists"]:
            continue
        out["playlists"][name] = {part: list(_part_places(part, part_value(values["playlists"][name], part),
                                                          have.get(part, MISSING)))
                                  for part in parts if part != "corrupt"}
    return out


def has_differences(result: Dict[str, Any]) -> bool:
    different = result["different"]
    return bool(result["missing"] or result["wrong_size"] or different["deployed"] or different["validity"]
                or different["settings"] or different["playlists"])
