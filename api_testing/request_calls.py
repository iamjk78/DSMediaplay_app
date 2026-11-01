import copy
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple, Optional, Union
from urllib.parse import quote, urljoin, urlparse
import requests
import urllib3.exceptions
from requests.adapters import HTTPAdapter
import json
from dataclasses import dataclass

LOGIN_TIMEOUT = 30  # seconds; without it a network black hole would freeze the window forever
SNAPSHOT_TIMEOUT = 60  # seconds; the server asks the player for the screenshot and waits for it
# (connect, read) seconds of every other request; without a timeout one request that never answers holds a whole
# deploy (and its STOP button) for good
REQUEST_TIMEOUT = (10, 60)
# Seconds to wait before the second and the third try of a request whose connection could not be made (a moment of
# trouble on the way to the server, or a server that answers only some of many requests in a row)
CONNECT_RETRY_DELAYS = (2, 5)
TOKEN_HEADER = "x-access-token"
# The one command of the check of the files on a player: it only reads the names in the folder of the media
PLAYER_MEDIA_DIR = "/home/pi/media"
PLAYER_FILES_COMMAND = f"ls -1A {PLAYER_MEDIA_DIR}"
PLAYER_COMMAND_TIMEOUT = (10, 30)  # (connect, read) seconds; a player that is silent for 30 s is skipped
SNAPSHOT_MAX_BYTES = 20 * 1024 * 1024
IMAGE_SIGNATURES = ((b"\x89PNG\r\n\x1a\n", ".png"), (b"\xff\xd8\xff", ".jpg"), (b"GIF8", ".gif"))

# The order of the days in the server's location schedule (`weekDays`, index 0 = Sunday), the way the web UI shows them
# (SU MO TU ... SA). Reading, writing, the CSV export and the input all use this one order.
WEEK_DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


def never_reached_the_server(error: requests.exceptions.RequestException) -> bool:
    """
    The connection was not made, so nothing of the request was sent and sending it again cannot do it twice. (A request
    that was sent and not answered is different: it may have been done, and only a reading one could be repeated.)
    """
    if isinstance(error, requests.exceptions.ConnectTimeout):
        return True
    if isinstance(error, requests.exceptions.ConnectionError):
        reason = getattr(error.args[0] if error.args else None, "reason", None)
        return isinstance(reason, (urllib3.exceptions.NewConnectionError, urllib3.exceptions.ConnectTimeoutError))
    return False


class _AssertHostnameAdapter(HTTPAdapter):
    """Verifies the server certificate against `assert_hostname` instead of the host that is connected to."""

    def __init__(self, assert_hostname: str, **kwargs) -> None:
        self._assert_hostname = assert_hostname
        super().__init__(**kwargs)

    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, assert_hostname=self._assert_hostname, **kwargs)


# The servers of the accounts: only for these the name check may use the hyphenated name (see below)
SERVER_DOMAINS = (".signage.dsmediaplay.com",)


def _assert_hostname_for(url: str) -> Optional[str]:
    """
    Wildcard certificates never match hostnames containing an underscore (e.g. shop_admin.signage...), although
    the server presents a valid certificate for them. The certificate chain is still verified; only the name
    check uses the hyphenated equivalent, which the wildcard covers.
    """
    host = urlparse(url).hostname or ""
    if "_" not in host or not host.endswith(SERVER_DOMAINS):  # not for any other host: that one must match as it is
        return None
    return host.replace("_", "-")


# "_jdoe", "_asmi", "_bwhi": an underscore and four letters ending the first part of the host name (before "." or the port)
USER_ABBREVIATION = re.compile(r"^(?P<main>[^.:@/]+)_[A-Za-z]{4}(?=[.:]|$)")


def main_account_url(url: str) -> str:
    """
    A user of an account (a collaborator) has an address of its own with the user's abbreviation at the end of the
    first part of the host name: https://acmeshop_jdoe.signage... belongs to the user "jdoe" of the account
    "acmeshop" and holds nothing but that user's own, empty installation. The players are at the address of the
    main account, the one without the abbreviation, which is where the web app takes the user when they switch
    to the main account. Only that first part of the host name is changed, so the address stays on the same server.

    The abbreviation is an underscore and exactly four letters: "acme_shp" or "shop_admin" are names of accounts
    and stay as they are.
    """
    parsed = urlparse(url)
    netloc = USER_ABBREVIATION.sub(r"\g<main>", parsed.netloc, count=1)  # on the text: a host name has any case
    return url if netloc == parsed.netloc else parsed._replace(netloc=netloc).geturl()


def local_time_of_day(iso: str) -> Optional[str]:
    """
    The "HH:MM" that stands for a time of the day stored as a date: the web app writes it next to the time (as
    `absoluteTime`) and so does this one. The times of the day are stored with the date 1970-01-01, when Central
    Europe was one hour ahead of UTC all the year (and the web app stores 23:00 as 22:00Z in summer as well).
    """
    try:
        moment = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (moment + timedelta(hours=1)).strftime("%H:%M")


def flatten(xss: List[Any]):
    return [x for xs in xss for x in xs]


def path_segment(name: str) -> str:
    """
    A name as one part of the path of a request. Written as it is, a "?" or "#" in it ends the path ("a?b.mp4" would
    delete the asset "a"), a "%" is read as the start of a code and a "/" as the end of the part.
    """
    return quote(name, safe="")


def label_pattern(name: str) -> str:
    """The search of labels takes a regular expression; this one matches the name itself and nothing else."""
    return re.sub(r"[.*+?^${}()|\[\]\\/]", r"\\\g<0>", name)


# /players is read in pages of this size, asked for explicitly instead of trusting the server's default one
PLAYERS_PER_PAGE = 500
MAX_PLAYER_PAGES = 1000


def player_key(player: Dict[str, Any]) -> str:
    """Tells players apart when a page is compared with the ones read before."""
    return player.get("_id") or json.dumps(player, sort_keys=True, default=str)


# Rows of a playlist can hold the name of an asset or of another playlist in these zones, next to the main file
ZONE_FIELDS = ("side", "bottom", "zone4", "zone5", "zone6")


# The zones of a layout in which a row of a playlist can name another file (the same table as the web interface has)
LAYOUT_ZONES = {
    "1": (), "2a": ("side",), "2b": ("side",), "2c": ("side",), "2d": ("side",),
    "3a": ("side", "bottom"), "3b": ("side", "bottom"), "3c": ("side", "bottom"), "3d": ("side", "bottom"),
    "4a": ("side", "bottom"), "4b": ("side", "bottom"), "4c": ("side", "bottom"), "4d": ("side", "bottom"),
    "2ap": (), "2bp": ("bottom",), "2ap270": (), "2bp270": ("bottom",),
    "custom": ZONE_FIELDS, "customp": ZONE_FIELDS, "customp270": ZONE_FIELDS,
}
# What a group's entry for a playlist takes over from the playlist itself
COPIED_PLAYLIST_SETTINGS = ("ads", "domination", "event", "keyPress", "onlineOnly", "audio")
NO_FILE_PREFIX = "_system"  # the files of the system are not synced as the files of a group


def _truthy(value: Any) -> bool:
    """What is true for the web interface (JavaScript): the string "false" is true, an empty list is true."""
    if value is None or value is False:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0 and value == value
    return value != ""


def _playlist_type(playlist: Dict[str, Any]) -> str:
    settings = playlist.get("settings") or {}
    for key, label in (("ads", "advt"), ("domination", "domination"), ("event", "event"), ("keyPress", "keyPress"),
                       ("audio", "audio")):
        feature = settings.get(key)
        if isinstance(feature, dict) and _truthy(feature.get("adPlaylist" if key == "ads" else "enable")):
            return label
    return "regular"


def prepare_group_playlists(entries: List[Dict[str, Any]], playlists: List[Dict[str, Any]],
                            logo: Optional[str] = None) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    What the web interface does with a group before it saves it (`GroupFunctions.listFiles`): the list of the files the
    group has to have on its players (`assets`), and in every entry for a playlist what is taken from the playlist.

    The server does not work the files of a group out of its playlists, it keeps what it is sent, and copies it to the
    players on Deploy: a group written with playlists and without their files has the names of the playlists on its
    players and nothing to play. The files are the files of every playlist of the group, what its rows name in the
    zones of the layout, the files of a playlist that is in a zone, the file of the playlist itself (`__name.json`), the
    template of the playlist, and the logo of the group.

    `entries` are the entries of the group for its playlists, `playlists` all the playlists of the account as the
    server has them. Returns copies: the entries (an entry without a name is dropped, the others have what the
    interface gives them) and the list of the files.
    """
    known: Dict[str, Dict[str, Any]] = {}
    for playlist in playlists:
        known.setdefault(playlist.get("name"), playlist)
    entries = copy.deepcopy(entries)
    files: List[str] = []

    def add(name: Any) -> None:
        if isinstance(name, str) and name and name not in files and not name.startswith(NO_FILE_PREFIX):
            files.append(name)

    for index in range(len(entries) - 1, -1, -1):  # from the last entry to the first, as the interface does
        entry = entries[index]
        name = entry.get("name")
        playlist = known.get(name) if name else None
        if playlist is None:
            if not name:
                del entries[index]
            continue
        rows = playlist.get("assets") or []
        zones = LAYOUT_ZONES.get(str(playlist.get("layout")), ZONE_FIELDS)
        for row in rows:
            add(row.get("filename"))
            for zone in zones:
                reference = row.get(zone)
                if not (isinstance(reference, str) and reference) or reference.startswith(NO_FILE_PREFIX):
                    continue
                add(reference)
                if reference.startswith("__"):  # another playlist in the zone: its files are needed too
                    end = reference.find(".json")
                    nested = known.get(reference[2:end] if end != -1 else reference[2:-1])
                    if nested and isinstance(nested.get("assets"), list):
                        for nested_row in nested["assets"]:
                            add(nested_row.get("filename"))
        own = f"__{name}.json"
        if own not in files:
            files.append(own)
        # other layouts keep a default templateName that is not a file of the account
        if str(playlist.get("layout")).startswith("custom") and playlist.get("templateName") \
                and playlist["templateName"] not in files:
            files.append(playlist["templateName"])

        settings = entry.get("settings") or {}
        taken = playlist.get("settings") or {}
        for key in COPIED_PLAYLIST_SETTINGS:
            if key in taken:
                settings[key] = taken[key]
            else:
                settings.pop(key, None)
        entry["settings"] = settings
        if name == "TV_OFF":
            entry["plType"] = "special"
        elif not rows:
            entry["skipForSchedule"], entry["plType"] = True, "no assets"
        else:
            entry["skipForSchedule"], entry["plType"] = False, _playlist_type(playlist)
    if logo and logo not in files:
        files.append(logo)
    return entries, files


def require_keyword(keyword: str) -> str:
    """An empty keyword is contained in every name, so removing "by keyword" with it would remove everything."""
    if not keyword or not keyword.strip():
        raise ValueError("The keyword must not be empty")
    return keyword


def zone_references(playlist: Dict[str, Any]) -> List[str]:
    """Names (of assets or playlists) that the rows of a playlist use in its zones."""
    return [row[field] for row in playlist.get("assets") or [] for field in ZONE_FIELDS
            if isinstance(row.get(field), str) and row[field]]


class ServerApiError(Exception):
    """Base class for ServerApi class related errors."""
    pass


class LoginError(Exception):
    """During login the token wasn't retrieved."""
    pass


@dataclass
class NameResolutionError(ServerApiError):
    """
    Name wasn't found on the server.

    Attributes
    ----------
    name : str
        The name that could not be found on the server.
    """
    name: str


def without_secrets(value: Any) -> Any:
    """A copy of request parameters without the session token, so that they can be shown or logged."""
    if isinstance(value, dict):
        return {key: without_secrets(item) for key, item in value.items()
                if str(key).lower() not in (TOKEN_HEADER, "token", "password")}
    return value


@dataclass
class ResponseError(ServerApiError):
    """
    The server refused a request: a non-200 code, or an answer that says it was not successful.

    The text of this error is shown to the user and written to the log, so it carries what went wrong (the status,
    the request and the server's own message) and never the session token.

    Attributes
    ----------
    params : dict
        The parameters of the failed request, without the token.
    status : int, optional
        The HTTP status of the answer.
    request : str
        "METHOD /endpoint" of the failed request.
    message : str
        The server's own description of the failure, if it gave one.
    """
    params: dict
    status: Optional[int] = None
    request: str = ""
    message: str = ""

    def __post_init__(self):
        self.params = without_secrets(self.params)
        self.args = (str(self),)  # the default text of an exception is made of the arguments it was created with

    def __str__(self):
        parts = [part for part in (f"HTTP {self.status}" if self.status else "", self.request, self.message) if part]
        return "The server refused the request" + (": " + ", ".join(parts) if parts else "")


class PlayerCommandError(ServerApiError):
    """
    A command on a player gave no usable answer.

    Attributes
    ----------
    reason : str
        "no_answer" (the player did not answer in time) or "failed" (it answered with an error).
    """
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class SnapshotError(ServerApiError):
    """
    A player snapshot could not be fetched.

    Attributes
    ----------
    reason : str
        One of "bad_url", "download", "not_image", "too_large".
    """
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def snapshot_reason(error: Exception) -> str:
    """Why a snapshot could not be taken, as the ending of the message key "snapshot_reason_<...>"."""
    if isinstance(error, SnapshotError):
        return error.reason
    if isinstance(error, (ResponseError, NameResolutionError)):
        return "server"
    return "download"


def snapshot_file_stem(player: str, moment: datetime) -> str:
    """The file name (without extension) of a snapshot: the player name is made of nothing that could leave the folder."""
    safe_name = re.sub(r"[^\w.-]+", "_", player).strip("._") or "player"
    return f"{safe_name}_{moment:%Y-%m-%d_%H-%M-%S}"


class ServerApi:
    def __init__(self, *, url: str, login: str, password: str) -> None:
        """
        Initializes the ServerApi with the given URL, login, and password.

        Parameters
        ----------
        url : str
            The base URL for the API. The address of a user of an account is replaced by the address of the main
            account (see `main_account_url`).
        login : str
            The login username.
        password : str
            The password for API access.
        """
        self._url = main_account_url(url)
        # What the log says when the address was replaced: the credentials go to another address than the one typed
        self.redirected_to = self._url if self._url != url else None
        self._login = login
        self._password = password
        self._assert_hostname = _assert_hostname_for(self._url)
        self._session_token = self._get_session_token()

    def __enter__(self) -> "ServerApi":
        """
        Enters the runtime context related to this object.

        Returns
        -------
        ServerApi
            The instance of the ServerApi class.
        """
        if self._session_token is None:
            self._session_token = self._get_session_token()
        return self

    def __exit__(self, exception_type, exception_value, exception_traceback) -> None:
        """
        Exits the runtime context related to this object. Logging out is of no interest to the result: what was done
        with the session is done, and an error here would report a successful action as a failed one.
        """
        self.close_quietly()

    def close_quietly(self) -> None:
        """Logs out, but a failure of that is of no interest: what has been fetched with the session stays valid."""
        try:
            self._close_session()
        except (requests.exceptions.RequestException, ServerApiError):
            pass

    def _close_session(self) -> None:
        """
        Sends request to close session and invalidates session token.
        """
        try:
            self._make_request("delete", "/session")
        except requests.exceptions.JSONDecodeError:
            pass
        finally:
            self._session_token = None

    def _get_session_token(self) -> str:
        """
        Returns a session token from the server.

        Returns
        -------
        str
            The session token.

        Raises
        ------
        LoginError
            If the login credentials are incorrect.
        """
        data = {
            "email": self._login,
            "password": self._password,
            "getToken": "true"
        }
        response = self._post(self._url + "/session", json=data, timeout=LOGIN_TIMEOUT)
        if response.status_code in (401, 403):
            raise LoginError
        if not response.ok:  # the server is down or broken: not the password that is wrong
            raise ResponseError(params={}, status=response.status_code, request="POST /session")
        body = response.json()  # a failed login answers with the JSON literal null
        token = body.get("token") if isinstance(body, dict) else None
        if not token:
            raise LoginError
        return token

    def _post(self, url: str, **kwargs) -> requests.Response:
        if self._assert_hostname is None:
            return requests.post(url, **kwargs)
        return self._request("post", url, **kwargs)

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        if self._assert_hostname is None:
            return requests.request(method, url, **kwargs)
        # A session per call, as requests.request does internally, so concurrent Deploy threads share nothing
        with requests.Session() as session:
            session.mount("https://", _AssertHostnameAdapter(self._assert_hostname))
            return session.request(method, url, **kwargs)

    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        url = f"{self._url}{endpoint}"
        # The token travels in a header, not in the address: an address ends up in error texts, logs and proxies
        kwargs["headers"] = {"Content-Type": "application/json", TOKEN_HEADER: self._session_token,
                             **kwargs.get("headers", {})}
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        for delay in (*CONNECT_RETRY_DELAYS, None):
            try:
                response = self._request(method, url, **kwargs)
                break
            except requests.exceptions.RequestException as error:
                if delay is None or not never_reached_the_server(error):
                    raise
                time.sleep(delay)

        failure = {"params": kwargs.get("params") or {}, "status": response.status_code,
                   "request": f"{method.upper()} {endpoint}"}
        if not response.ok:
            raise ResponseError(**failure)
        response_json = response.json()
        if not response_json.get("success", False):
            raise ResponseError(**failure, message=str(response_json.get("stat_message") or ""))
        return response_json

    def get_player_names(self) -> List[str]:
        """
        Returns a list of player names.

        Returns
        -------
        list of str
            A list of player names.
        """
        return [obj.get("name", "") for obj in self.get_player_objects()]

    def get_asset_names(self) -> List[str]:
        response = self._make_request("get", "/files")
        return [obj.get("name", "") for obj in response.get("data", {}).get("dbdata", [])]

    def get_screen_off_players(self) -> List[str]:
        """
        Returns a list of player names with screens off.

        Returns
        -------
        list of str
            A list of player names.
        """
        return [obj.get("name", "") for obj in self.get_player_objects() if not obj.get("playlistOn", True)]

    def get_disconnected_players(self) -> List[str]:
        """
        Returns a list of disconnected player names.

        Returns
        -------
        list of str
            A list of player names.
        """
        return [obj.get("name", "") for obj in self.get_player_objects() if not obj.get("isConnected", None)]

    def get_online_players(self) -> List[str]:

        return [
            obj.get("name", "")
            for obj in self.get_player_objects()
            if obj.get("isConnected", True) and obj.get("playlistOn", True)
        ]

    def get_players_for_deploy(self, group_names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Retrieves players (optionally filtered by a list of groups) with the fields needed
        to drive a sequential per-player deploy: id, group id/name and connection status.

        Parameters
        ----------
        group_names : Optional[List[str]]
            If given, only players belonging to one of these groups are returned.

        Returns
        -------
        list of dict
            Each dict has keys: name, _id, group_id, group_name, isConnected.
        """
        players = []
        for obj in self.get_player_objects():
            group = obj.get("group") or {}
            players.append({
                "name": obj.get("name", ""),
                "_id": obj.get("_id", ""),
                "group_id": group.get("_id", ""),
                "group_name": group.get("name", ""),
                "isConnected": obj.get("isConnected", False)
            })

        if group_names is not None:
            players = [player for player in players if player["group_name"] in group_names]

        return players

    def trigger_player_deploy(self, player_id: str, group_id: str, group_name: str) -> Dict[str, Any]:
        """
        Forces a single player to check in with the server for new content immediately,
        by re-sending its current group assignment (does not affect other players in the group).

        Parameters
        ----------
        player_id : str
            The unique ID of the player.
        group_id : str
            The unique ID of the player's current group.
        group_name : str
            The name of the player's current group.

        Returns
        -------
        json
            The response from the server.
        """
        request_body = {
            "group": {
                "_id": group_id,
                "name": group_name
            }
        }
        return self._make_request("post", f"/players/{player_id}", json=request_body)

    def get_player_names_by_keyword(self, key_word: str) -> List[str]:
        """
        Returns a list of player names filtered from the server by keyword.

        Returns
        -------
        list of str
            A list of player names.
        """
        response = self._make_request("get", "/players", params={"string": key_word})
        return [obj.get("name", "") for obj in response.get("data", {}).get("objects", [])]

    def get_group_names(self) -> List[str]:
        """
        Returns a list of group names.

        Returns
        -------
        list of str
            A list of group names.
        """
        response = self._make_request("get", "/groups")
        return [obj.get("name", "") for obj in response.get("data", [])]

    def get_player_id_by_name(self, name: str) -> str:
        """
        Creates request to find unique id of player by its name.

        Parameters
        ----------
        name : str
            The name of the player.

        Returns
        -------
        str
            The unique ID of the player.

        Raises
        ------
        NameResolutionError
            If the name wasn't present among all names of players.
        """
        ids = self._player_ids_by_name()
        if name not in ids:  # perhaps a player that was made in the meantime: one more look
            ids = self._player_ids_by_name(refresh=True)
        if name in ids:
            return ids[name]
        raise NameResolutionError(name)

    def _player_ids_by_name(self, refresh: bool = False) -> Dict[str, str]:
        """
        The ids of all the players by name, read once for this session: an action that does something to each of 500
        players asked for the whole list of 500 players 500 times. Of two players with one name the first counts.
        """
        ids = getattr(self, "_player_ids", None)
        if ids is None or refresh:
            ids = {}
            for obj in self.get_player_objects():
                ids.setdefault(obj.get("name", ""), obj["_id"])
            self._player_ids = ids
        return ids

    def get_asset_id_by_name(self, name: str) -> str:
        """
        Creates request to find unique id of asset by its name.

        Parameters
        ----------
        name : str
            The name of the asset.

        Returns
        -------
        str
            The unique ID of the asset.

        Raises
        ------
        NameResolutionError
            If the name doesn't belong to any assets.
        """
        response = self._make_request("get", f"/files/{path_segment(name)}")
        _id = response["data"].get("dbdata", {}).get("_id", False)
        if _id:
            return _id

        raise NameResolutionError(name)

    def get_label_id_by_name(self, name: str) -> str:
        """
        Creates request to find unique id of label by its name.

        Parameters
        ----------
        name : str
            The name of the label.

        Returns
        -------
        str
            The unique ID of the label.

        Raises
        ------
        NameResolutionError
            If the name wasn't present among all names of players.
        """
        response = self._make_request("get", "/labels", params={"string": label_pattern(name)})
        filtered = [entity["_id"] for entity in response.get("data", []) if name == entity.get("name", "")]
        if len(filtered) == 1:
            return filtered[0]
        raise NameResolutionError(name)

    def get_group_id_by_name(self, name: str) -> str:
        """
        Creates request to find unique id of group by its name.

        Parameters
        ----------
        name : str
            The name of the group.

        Returns
        -------
        str
            The unique ID of the group.

        Raises
        ------
        NameResolutionError
            If the name wasn't present among all names of groups.
        """
        response = self._make_request("get", "/groups", params={"string": name})  # a search: the name itself is among the finds
        filtered = [entity["_id"] for entity in response.get("data", []) if name == entity.get("name", "")]
        if len(filtered) == 1:
            return filtered[0]
        raise NameResolutionError(name)

    def get_groups_playlists(self) \
            -> Dict[str, List[Tuple[str, Optional[str], Optional[str], Optional[str], Optional[str]]]]:
        """
        Retrieves group playlists.

        Returns
        -------
        dict
            A dictionary where keys are group names and values are lists of playlist details.
        """
        response = self._make_request("get", "/groups")
        group_playlist = {}
        for obj in response.get("data", []):
            name = obj.get("name", "")
            group_playlist[name] = []
            for playlist in obj.get("playlists", []):
                playlist_name = playlist.get("name", "")
                settings = playlist.get("settings", {})
                group_playlist[name].append((
                    playlist_name,
                    settings.get("startdate"),
                    settings.get("enddate"),
                    settings.get("starttime"),
                    settings.get("endtime")
                ))
        return group_playlist

    def get_playlist_names(self) -> List[str]:
        """
        Returns a list of playlist names.

        Returns
        -------
        list of str
            A list of playlist names.
        """
        response = self._make_request("get", "/playlists")
        return [obj.get("name", "") for obj in response.get("data", "")]

    def _playlist_objects(self) -> List[Dict[str, Any]]:
        """All playlists of the account as the server has them (with their rows), read once for the whole session."""
        if getattr(self, "_playlist_cache", None) is None:
            self._playlist_cache = self._make_request("get", "/playlists").get("data") or []
        return self._playlist_cache

    def _set_group_playlists(self, group_id: str, group: str, playlists: List[Dict],
                             details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Helper function to set playlists for a group. The files of the group (`assets`) are sent with them, worked
        out as the web interface does (see prepare_group_playlists): without them the players of the group get the names
        of the playlists on Deploy and nothing to play.

        Parameters
        ----------
        group_id : str
            The unique ID of the group.
        group : str
            The name of the group.
        playlists : list of dict
            A list of playlist dictionaries.
        details : dict, optional
            The group as the server has it now (its logo is one of its files); read here when not given.

        Returns
        -------
        json
            The response from the server.
        """
        if details is None:
            details = self.get_group_details(group_id)
        playlists, assets = prepare_group_playlists(playlists, self._playlist_objects(), details.get("logo"))
        request_body = {
            "_id": group_id,
            "name": group,
            "playAllEligiblePlaylists": "true",  # on purpose: the CMS depends on it, do not make it optional
            "playlists": playlists,
            "assets": assets
        }
        return self._make_request("post", f"/groups/{group_id}", json=request_body)

    def _keep_what_the_group_has(self, group_id: str, written: List[Tuple[Dict, Dict]],
                                 managed: Tuple[str, ...], details: Optional[Dict[str, Any]] = None) -> List[Dict]:
        """
        The tables and the CSV know only a few settings of a playlist in a group (dates, days of the week, times).
        The server keeps more of them (ads, audio, dominance, "skip for schedule", the type of the playlist) and takes
        in a write exactly what it is sent, so a playlist written from a table alone lost all of them.

        Every playlist written (the entry to send and what the table says about it) is therefore matched (by name, in
        order, as a group can hold one twice) with the one the group has now: if the table says the same as the group
        already does, the group's own entry is sent back untouched; if not, the settings the table owns (`managed`)
        are replaced and all the others stay.
        """
        current = {}
        for existing in (details if details is not None else self.get_group_details(group_id)).get("playlists", []):
            current.setdefault(existing.get("name", ""), []).append(existing)

        result = []
        for built, shown in written:
            candidates = current.get(built["name"])
            if not candidates:
                result.append(built)
                continue
            existing = candidates.pop(0)
            settings = existing.get("settings") or {}
            switches_agree = all((str(settings.get(switch)).lower() == "true") == (switch in built["settings"])
                                 for switch in ("durationEnable", "timeEnable") if switch in managed)
            if switches_agree and all((settings.get(key) or None) == (value or None) for key, value in shown.items()):
                result.append(existing)
                continue
            kept = {key: value for key, value in settings.items() if key not in managed}
            result.append({**existing, "settings": {**kept, **built["settings"]}})
        return result

    def set_playlist_to_group(self, group: str,
                              playlists: List[Tuple[str, Optional[str], Optional[str], Optional[str], Optional[str]]]) \
            -> Dict[str, Any]:
        """
        Updates the group's playlists with the specified playlist tuples.

        Parameters
        ----------
        group : str
            The name of the group.
        playlists : list of tuples
            List of tuples where each tuple contains playlist name, start date, end date, start time, and end time.

        Returns
        -------
        json
            The response from the server.
        """
        group_id = self.get_group_id_by_name(group)
        written = [
            ({
                "name": playlist_name,
                "settings": {
                    **({"durationEnable": "true", "startdate": start_date, "enddate": end_date}
                       if start_date and end_date else {}),
                    **({"timeEnable": "true", "starttime": start_time, "endtime": end_time}
                       if start_time and end_time else {})
                }
            }, {"startdate": start_date, "enddate": end_date, "starttime": start_time, "endtime": end_time})
            for playlist_name, start_date, end_date, start_time, end_time in playlists
        ]
        managed = ("durationEnable", "startdate", "enddate", "timeEnable", "starttime", "endtime")
        details = self.get_group_details(group_id)
        return self._set_group_playlists(group_id, group, self._keep_what_the_group_has(group_id, written, managed, details),
                                         details)

    def set_playlist_to_group_detailed(self, group: str,
                                       playlists: List[Tuple[str, Optional[str], Optional[str], Optional[List[int]], Optional[str], Optional[str]]]) -> Dict[str, Any]:
        """
        Sets detailed playlists for a group.

        Parameters
        ----------
        group : str
            The name of the group.
        playlists : list of tuples
            List of tuples containing playlist details.

        Returns
        -------
        json
            The response from the server.
        """
        group_id = self.get_group_id_by_name(group)
        written = []

        for playlist_name, startdate, enddate, weekdays, starttime, endtime in playlists:
            playlist = {
                "name": playlist_name,
                "settings": {},
            }

            if startdate or enddate:
                playlist["settings"]["durationEnable"] = "true"
                if startdate:
                    playlist["settings"]["startdate"] = startdate
                if enddate:
                    playlist["settings"]["enddate"] = enddate

            if weekdays:
                playlist["settings"]["weekdays"] = weekdays

            if starttime or endtime:
                playlist["settings"]["timeEnable"] = "true"
                playlist["settings"]["starttime"] = starttime or "0:00"
                playlist["settings"]["endtime"] = endtime or "23:59"

            written.append((playlist, {"startdate": startdate, "enddate": enddate, "weekdays": weekdays,
                                       "starttime": starttime, "endtime": endtime}))

        managed = ("durationEnable", "startdate", "enddate", "weekdays", "timeEnable", "starttime", "endtime")
        details = self.get_group_details(group_id)
        return self._set_group_playlists(group_id, group, self._keep_what_the_group_has(group_id, written, managed, details),
                                         details)

    def set_group_to_player(self, group: str, player: str) -> Dict[str, Any]:
        """
        Sets player to given group.

        Parameters
        ----------
        group : str
            The name of the group.
        player : str
            The name of the player.

        Returns
        -------
        json
            The response from the server.
        """
        player_id = self.get_player_id_by_name(player)
        group_id = self.get_group_id_by_name(group)
        request_body = {
            "group": {
                "_id": group_id,
                "name": group
            }
        }
        return self._make_request("post", f"/players/{player_id}", json=request_body)

    def get_players_groups(self) -> List[Tuple[str, str]]:
        """
        Retrieves the groups of all players.

        Returns
        -------
        list of tuples
            A list of tuples containing player names and their group names.
        """
        return [
            (obj.get("name", ""), (obj.get("group") or {}).get("name", ""))  # a player without a group: null
            for obj in self.get_player_objects()
        ]

    def get_all_playlists_details(self) -> List[Tuple[str, List[str]]]:
        """
        Retrieves details of all playlists including validity periods and lists of assets.

        Returns
        -------
        list of tuples
            A list of tuples where each tuple contains the playlist name,
            start date, end date, and a list of assets with corresponding duration.
        """
        response = self._make_request("get", "/playlists")

        return [
            (playlist.get("name", ""), [asset.get("filename", "") for asset in playlist.get("assets", [])])
            for playlist in response.get("data", [])
        ]

    def get_groups_playlists_details(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Retrieves detailed information about groups and their playlists.

        Returns
        -------
        dict
            A dictionary where each key is a group name and the value is a list
            of dictionaries containing playlist details.
        """
        response = self._make_request("get", "/groups")
        group_playlist_details = {}
        for group in response.get("data", []):
            group_name = group.get("name", "")
            group_playlist_details[group_name] = [
                {
                    "playlist_name": playlist.get("name", ""),
                    "start_date": playlist.get("settings", {}).get("startdate"),
                    "end_date": playlist.get("settings", {}).get("enddate"),
                    "days_of_week": playlist.get("settings", {}).get("weekdays"),
                    "start_time": playlist.get("settings", {}).get("starttime"),
                    "end_time": playlist.get("settings", {}).get("endtime")
                }
                for playlist in group.get("playlists") or []
            ]
        return group_playlist_details

    def set_assets_to_playlist(self, playlist: str, assets: List[str]) -> Dict[str, Any]:
        """
        Makes the assets of the playlist the listed ones, in that order.

        The server keeps more about an asset in a playlist than its name (the duration it is shown for, full screen,
        the zones), and takes in a write exactly what it is sent. So an asset that the playlist has already is sent
        back as the playlist has it, and only one that is new gets the defaults. (Writing every asset from its name
        alone reset the durations of all the others every time one asset was taken out.)

        Parameters
        ----------
        playlist : str
            The name of the playlist.
        assets : list of str
            The filenames of the assets, in the order they are to play.

        Returns
        -------
        json
            The response from the server.
        """
        current = {}
        for existing in (self._make_request("get", f"/playlists/{path_segment(playlist)}").get("data") or {}) \
                .get("assets") or []:
            current.setdefault(existing.get("filename"), []).append(existing)

        request_body = {
            "playlist": playlist,
            "assets": assets
        }
        response_assets = self._make_request("post", "/playlistfiles", json=request_body)
        if not response_assets.get("success", False):
            response_assets.status_code = 400
            return response_assets

        settings_request_body = {
            "name": playlist,
            "assets": [
                current[asset_name].pop(0) if current.get(asset_name) else
                {
                    "filename": asset_name,
                    "selected": "true",
                    "dragSelected": "true",
                    "option": {
                        "main": "true"
                    }
                }
                for asset_name in assets
            ]
        }
        return self._make_request("post", f"/playlists/{path_segment(playlist)}", json=settings_request_body)

    def get_group_details(self, group_id: str) -> Dict:
        """
        Retrieves the details of a group by its ID.

        Parameters
        ----------
        group_id : str
            The unique ID of the group.

        Returns
        -------
        dict
            The details of the group.
        """
        return self._make_request("get", f"/groups/{group_id}")["data"]

    def update_group_details(self, group_id: str, group_details: dict) -> None:
        """
        Updates the details of a group.

        Parameters
        ----------
        group_id : str
            The unique ID of the group.
        group_details : dict
            The updated group details.

        Raises
        ------
        requests.exceptions.RequestException
            If the request fails.
        """
        self._make_request("post", f"/groups/{group_id}", json=group_details)

    def remove_playlists_by_keyword_from_group(self, group: str, keyword: str) -> List[str]:
        """
        Removes playlists containing the keyword from the specified group.

        Parameters
        ----------
        group : str
            The name of the group.
        keyword : str
            The keyword to search for in playlist names.

        Returns
        -------
        list of str
            A list of removed playlist names.
        """
        require_keyword(keyword)
        group_id = self.get_group_id_by_name(group)
        group_details = self.get_group_details(group_id)

        new_playlists = []
        removed = []

        for playlist in group_details.get("playlists") or []:
            if keyword in playlist.get("name", ""):
                removed.append(playlist["name"])
            else:
                new_playlists.append(playlist)

        if removed:
            group_details["playlists"] = new_playlists
            self.update_group_details(group_id, group_details)

        return removed

    def remove_assets_by_keyword_from_playlist(self, playlist_name: str, keyword: str) -> List[str]:
        """
        Removes assets containing the keyword from the specified playlist.

        Parameters
        ----------
        playlist_name : str
            The name of the playlist.
        keyword : str
            The keyword to search for in asset filenames.

        Returns
        -------
        list of str
            A list of removed asset filenames.
        """
        require_keyword(keyword)
        all_playlists = self.get_all_playlists_details()

        for name, assets in all_playlists:
            if name == playlist_name:
                new_assets = []
                removed_assets = []

                for asset_name in assets:
                    if keyword in asset_name:
                        removed_assets.append(asset_name)
                    else:
                        new_assets.append(asset_name)

                if removed_assets:
                    self.set_assets_to_playlist(playlist_name, new_assets)

                return removed_assets

        raise NameResolutionError(playlist_name)

    def set_player_note(self, player_name: str, note: str) -> Dict[str, Any]:
        """
        Updates the note for the specified player.

        Parameters
        ----------
        player_name : str
            The name of the player.
        note : str
            The note to be updated.

        Returns
        -------
        json
            The response from the server.
        """
        player_id = self.get_player_id_by_name(player_name)
        request_body = {"notes": note}

        return self._make_request("post", f"/players/{player_id}", json=request_body)

    def get_player_locations(self) -> List[Tuple[str, str]]:
        """
        Retrieves the locations of all players.

        Returns
        -------
        list of tuples
            A list of tuples containing player names and their configuration locations.
        """
        return [(obj.get("name", ""), obj.get("configLocation", "ERROR")) for obj in self.get_player_objects()]

    def set_player_config_location(self, player_name: str, config_location: str) -> Dict[str, Any]:
        """
        Updates the player's configuration location.

        Parameters
        ----------
        player_name : str
            The name of the player.
        config_location : str
            The new configuration location for the player.

        Returns
        -------
        json
            The response from the server.
        """
        player_id = self.get_player_id_by_name(player_name)
        request_body = {"configLocation": config_location}

        return self._make_request("post", f"/players/{player_id}", json=request_body)

    def get_player_notes(self) -> List[Tuple[str, str]]:
        """
        Retrieves the notes for all players.

        Returns
        -------
        list of tuples
            A list of tuples containing player names and their notes.
        """
        return [(obj["name"], obj.get("notes", "")) for obj in self.get_player_objects()]

    def get_labels(self) -> List[str]:
        """
        Retrieves all labels.

        Returns
        -------
        list of str
            A list of label names.
        """
        response = self._make_request("get", "/labels/")
        return [obj["name"] for obj in response.get("data", []) if obj.get("name")]  # a label without a name exists

    def get_additional_playlists(self) -> List[Tuple[str, List[str]]]:
        return [(obj.get("name", ""), obj.get("playlists", [])) for obj in self.get_player_objects()]

    def set_player_additional_playlist(self, player_name: str, additional_playlists: List[str]) -> Dict[str, Any]:
        player_id = self.get_player_id_by_name(player_name)
        request_body = {"playlists": additional_playlists}

        return self._make_request("post", f"/players/{player_id}", json=request_body)

    def set_player_labels(self, player_name: str, labels: List[str]) -> Dict[str, Any]:
        """
        Updates the labels for the specified player.

        Parameters
        ----------
        player_name : str
            The name of the player.
        labels : list of str
            The labels to be updated.

        Returns
        -------
        json
            The response from the server.
        """
        player_id = self.get_player_id_by_name(player_name)
        request_body = {"labels": labels}

        return self._make_request("post", f"/players/{player_id}", json=request_body)

    def get_player_labels(self) -> List[Tuple[str, List[str]]]:
        """
        Retrieves the labels for all players.

        Returns
        -------
        list of tuples
            A list of tuples containing player names and their labels.
        """
        return [(obj.get("name", ""), obj.get("labels", [])) for obj in self.get_player_objects()]

    def get_assets_labels(self) -> List[Tuple[str, List[str]]]:
        """
        Retrieves the labels for all players.

        Returns
        -------
        list of tuples
            A list of tuples containing player names and their labels.
        """
        response = self._make_request("get", "/files")
        return [(obj.get("name"), obj.get("labels", [])) for obj in response.get("data", {}).get("dbdata", [])]

    def get_group_labels(self) -> List[Tuple[str, List[str]]]:
        """
        Retrieves the labels for all players.

        Returns
        -------
        list of tuples
            A list of tuples containing player names and their labels.
        """
        response = self._make_request("get", "/groups")
        return [(obj.get("name", ""), obj.get("labels", [])) for obj in response.get("data", [])]

    def get_location_names(self) -> List[str]:
        """
        Retrieves the names of all locations.

        Returns
        -------
        list of str
            A list of location names.
        """
        response = self._make_request("get", "/locations")
        return [location.get("configLocation", "") for location in response.get("data", [])]

    def get_locations(self) -> List[Dict[str, Dict[str, Dict[str, str]]]]:
        """
        Retrieves location settings.

        Returns
        -------
        list of dict
            A list of dictionaries containing location names and their ON/OFF times.
        """
        response = self._make_request("get", "/locations")
        locations_data = []

        for location in response["data"]:
            location_name = location.get('configLocation', "")
            toggle_rows = location.get('toggleRows') or []
            times = {day: {"on": "", "off": ""} for day in WEEK_DAYS}

            for row in toggle_rows:
                on_time = row.get('turnOn') or ""
                off_time = row.get('turnOff') or ""
                for i, is_active in enumerate(row.get('weekDays', [])):
                    if is_active:
                        day = list(times.keys())[i]
                        times[day]["on"] = on_time
                        times[day]["off"] = off_time

            location_data = {location_name: times}
            locations_data.append(location_data)

        return locations_data

    def set_location(self, location_name: str, times: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
        """
        Sets the location settings.

        Parameters
        ----------
        location_name : str
            The name of the location.
        times : dict
            A dictionary with days of the week as keys and their corresponding ON/OFF times as values.

        Returns
        -------
        json
            The response from the server.
        """
        toggle_rows = self._create_toggle_rows(times)
        request_body = {
            "configLocation": location_name,
            "toggleRows": toggle_rows
        }
        return self._make_request("post", "/location-settings/", json=request_body)

    @staticmethod
    def _create_toggle_rows(times: Dict[str, Dict[str, str]]) -> List[Dict]:
        """
        Creates the toggle rows for the request body based on the time dictionary.

        Days with the same ON/OFF times share one row (as when the schedule is set in the web UI); the rows
        follow the order in which their first day appears.

        Parameters
        ----------
        times : dict
            A dictionary containing the ON/OFF times for each day of the week.

        Returns
        -------
        list
            A list of toggle rows for the request body.
        """
        rows_by_times: Dict[tuple, Dict] = {}
        for i, day in enumerate(WEEK_DAYS):
            on_time = times[day]["on"]
            off_time = times[day]["off"]
            if on_time or off_time:
                row = rows_by_times.setdefault((on_time, off_time), {
                    "turnOn": on_time,
                    "turnOff": off_time,
                    "weekDays": [False] * 7
                })
                row["weekDays"][i] = True
        return list(rows_by_times.values())

    def rename_group(self, old_name: str, new_name: str) -> Dict[str, Any]:
        """
        Renames a group.

        Parameters
        ----------
        old_name : str
            The current name of the group.
        new_name : str
            The new name of the group.

        Returns
        -------
        json
            The response from the server.
        """
        group_id = self.get_group_id_by_name(old_name)
        request_body = {"name": new_name}

        response = self._make_request("post", f"/groups/{group_id}", json=request_body)
        response["data"]["old_name"] = old_name
        return response

    def get_players_details(self) \
            -> List[Tuple[str, str, Optional[str], Optional[str], str, str, Optional[str], Optional[str]]]:
        """
        Retrieves detailed information about the players.

        Returns
        -------
        tuple
            A tuple containing player details: (name, online_status, last_connection, last_sync,
            sw_version, ip_address, uptime, last_temperature)
        """
        data = self.get_player_objects()

        return [(
            obj["name"],
            obj.get("tvStatus", None),
            obj.get("lastReported", None),
            obj.get("lastUpload", None),
            obj.get("version", None),
            obj.get("ip", None),
            obj.get("uptime", None),
            obj.get("piTemperature", None)
        ) for obj in data]

    def get_group_settings(self) -> List[Tuple[
            str,
            Optional[str],
            Optional[str],
            str,
            str,
            Optional[str],
            Optional[str],
            Optional[str],
            Optional[str],
            Optional[str]]]:
        """
        Retrieves group settings including display resolution, orientation, auto-restart, and auto-deploy.

        Returns
        -------
        list of tuples
            A list of tuples where each tuple contains group name,
            resolution, orientation, auto-restart, and auto-deploy.
        """
        response = self._make_request("get", "/groups")
        group_settings = [
            (
                group["name"],
                group.get("resolution"),
                group.get("orientation"),
                group["reboot"].get("time", None) if group.get("reboot", {}).get("enable") else None,
                group.get("everydayDeployTime", None) if group.get("deployEveryday") else None,
                group.get("combineDefaultPlaylist", None),
                group.get("playAllEligiblePlaylists", None),
                group.get("sleep", {}).get("ontime", None) if group.get("sleep", {}).get("enable") else None,
                group.get("sleep", {}).get("offtime", None) if group.get("sleep", {}).get("enable") else None,
                group.get("selectedVideoPlayer", None)
            )
            for group in response.get("data", [])
        ]
        return group_settings

    def set_group_settings(self, group: str, resolution: str, orientation: str, reboot_time: Optional[str],
                           deploy_everyday_time: Optional[str], combine_playlist: bool, all_eligible: bool,
                           on_time: Optional[str], off_time: Optional[str], video_player: Optional[str]) -> Dict[str, Any]:
        """
        Updates the settings for the specified group.

        Parameters
        ----------
        group : str
            The name of the group.
        resolution : str
            The resolution setting for the group.
        orientation : str
            The orientation setting for the group.
        reboot_time : Optional[str]
            The time for auto-restart. If None, auto-restart is disabled.
        deploy_everyday_time : Optional[str]
            The time for auto-deploy. If None, auto-deploy is disabled.
        combine_playlist: bool
        all_eligible: bool
        on_time: Optional[str]
        off_time: Optional[str]


        Returns
        -------
        json
            The response from the server.
        """
        group_id = self.get_group_id_by_name(group)
        request_body = {
            "resolution": resolution,
            "orientation": orientation,
            "combineDefaultPlaylist": combine_playlist,
            "playAllEligiblePlaylists": all_eligible,
            "sleep": {
                "enable": False
            },
            "selectedVideoPlayer": video_player
        }

        if reboot_time:
            reboot = {"enable": True, "time": reboot_time}
            if local_time := local_time_of_day(reboot_time):
                reboot["absoluteTime"] = local_time  # the web app writes it too, the time as the person sees it
            request_body.update({"reboot": reboot})
        else:
            request_body.update({
                "reboot": {
                    "enable": False
                }
            })

        if deploy_everyday_time:
            request_body.update({
                "deployEveryday": True,
                "everydayDeployTime": deploy_everyday_time
            })
        else:
            request_body.update({
                "deployEveryday": False
            })

        if on_time and off_time:
            request_body.update({
                "sleep": {
                    "enable": True,
                    "ontime": on_time,
                    "offtime": off_time
                }
            })

        return self._make_request("post", f"/groups/{group_id}", json=request_body)

    def get_location_id_by_name(self, name: str) -> str:
        """
        Fetches the unique ID of a location by its name.

        Parameters
        ----------
        name : str
            The name of the location.

        Returns
        -------
        str
            The unique ID of the location.

        Raises
        ------
        NameResolutionError
            If the name wasn't present among all names of locations.
        """
        response = self._make_request("get", "/locations")
        for location in response.get("data", ""):
            if location.get("configLocation", "") == name:
                return location["_id"]
        raise NameResolutionError(name)

    def rename_location(self, old_name: str, new_name: str) -> Dict[str, Any]:
        """
        Renames a location from the old name to the new name.

        Parameters
        ----------
        old_name : str
            The current name of the location.
        new_name : str
            The new name to assign to the location.

        Returns
        -------
        json
            The response from the server.
        """
        location_id = self.get_location_id_by_name(old_name)
        request_body = {
            "_id": location_id,
            "configLocation": new_name
        }

        response = self._make_request("post", f"/locations/{location_id}", json=request_body)
        response["data"]["old_name"] = old_name
        return response

    def rename_player(self, old_name: str, new_name: str) -> Dict[str, Any]:
        """
        Renames a player from the old name to the new name.

        Parameters
        ----------
        old_name : str
            The current name of the player.
        new_name : str
            The new name to assign to the player.

        Returns
        -------
        json
            The response from the server.
        """
        player_id = self.get_player_id_by_name(old_name)
        request_body = {
            "_id": player_id,
            "name": new_name
        }

        response = self._make_request("post", f"/players/{player_id}", json=request_body)
        self._player_ids = None  # the names have changed
        response["data"]["old_name"] = old_name
        return response

    def remove_expired_playlists_from_group(self, group: str) -> List[str]:
        """
        Removes expired playlists from the specified group.

        Parameters
        ----------
        group : str
            The name of the group.

        Returns
        -------
        list of str
            A list of removed playlist names.
        """
        group_id = self.get_group_id_by_name(group)
        group_details = self.get_group_details(group_id)

        new_playlists = []
        removed = []
        current_date = datetime.now().date().isoformat()

        for playlist in group_details.get("playlists") or []:
            settings = playlist.get("settings") or {}
            end_date = settings.get("enddate")
            # a date kept in a playlist whose date restriction is switched off (the web does that) restricts nothing
            if str(settings.get("durationEnable")).lower() == "true" and end_date and end_date[:10] < current_date:
                removed.append(playlist["name"])
            else:
                new_playlists.append(playlist)

        if removed:
            group_details["playlists"] = new_playlists
            self.update_group_details(group_id, group_details)

        return removed

    def create_location(self, name: str) -> Dict[str, Any]:
        """
        Creates a new location with the given name.

        Parameters
        ----------
        name : str
            The name of the new location.

        Returns
        -------
        json
            The response from the server.
        """
        request_body = {"configLocation": name}

        return self._make_request("post", "/locations/", json=request_body)

    def create_group(self, name: str) -> Dict[str, Any]:
        """
        Creates a new group with the given name.

        Parameters
        ----------
        name : str
            The name of the new group.

        Returns
        -------
        json
            The response from the server.
        """
        request_body = {"name": name}

        return self._make_request("post", "/groups/", json=request_body)

    def create_player(self, name: str) -> Dict[str, Any]:
        """
        Creates a new player with the given name.

        Parameters
        ----------
        name : str
            The name of the new player.

        Returns
        -------
        json
            The response from the server.
        """
        request_body = {"name": name}

        response = self._make_request("post", "/players/", json=request_body)
        self._player_ids = None  # there is one more
        return response

    def create_playlist(self, name: str) -> Dict[str, Any]:
        """
        Creates a new playlist with the given name.

        Parameters
        ----------
        name : str
            The name of the new playlist.

        Returns
        -------
        json
            The response from the server.
        """
        request_body = {"file": name}

        return self._make_request("post", "/playlists/", json=request_body)

    def create_label(self, name: str) -> Dict[str, Any]:
        """
        Creates a new label with the given name.

        Parameters
        ----------
        name : str
            The name of the new label.

        Returns
        -------
        json
            The response from the server.
        """
        request_body = {"name": name}

        return self._make_request("post", "/labels/", json=request_body)

    def get_players_by_label(self, label_name: str) -> List[str]:
        return [
            obj.get("name", "")
            for obj in self.get_player_objects() if label_name in obj.get("labels", [])
        ]

    def get_groups_by_label(self, label_name: str) -> List[str]:
        response = self._make_request("get", "/groups")
        return [obj.get("name", "") for obj in response.get("data", []) if label_name in obj.get("labels", [])]

    def get_assets_by_label(self, label_name: str) -> List[str]:
        response = self._make_request("get", "/files")
        return [
            obj.get("name", "")
            for obj in response.get("data", {}).get("dbdata", []) if label_name in obj.get("labels", [])
        ]

    def get_playlists_by_label(self, label_name: str) -> List[str]:
        response = self._make_request("get", "/playlists")
        return [obj.get("name", "") for obj in response.get("data", []) if label_name in obj.get("labels", [])]

    def get_locations_by_label(self, label_name: str) -> List[str]:
        response = self._make_request("get", "/locations")
        return [
            obj.get("configLocation", "")
            for obj in response.get("data", []) if label_name in obj.get("labels", [])
        ]

    def get_versions(self) -> List[Tuple[str, str]]:
        """
        Retrieves the software versions for all players.

        Returns
        -------
        list of tuples
            A list of tuples containing player names and their software versions.
        """
        return [(obj["name"], obj.get("version", "N/A")) for obj in self.get_player_objects()]

    def player_update(self, name: str) -> Dict[str, Any]:
        """
        Initiates a software update for the specified player.

        Parameters
        ----------
        name : str
            The name of the player.

        Returns
        -------
        json
            The response from the server.
        """
        player_id = self.get_player_id_by_name(name)

        return self._make_request("post", f"/swupdate/{player_id}")

    def get_unused_groups(self) -> List[str]:

        all_groups = self.get_group_names()
        assigned_groups = {group for _, group in self.get_players_groups()}
        return [group for group in all_groups if group not in assigned_groups]

    def get_empty_groups(self) -> List[str]:
        groups = self._make_request("get", f"/groups")
        return [group.get("name", "") for group in groups.get("data", {}) if len(group.get("playlists", [])) in [0, 1]]

    def get_unused_playlists(self) -> List[str]:
        """
        Fetches playlists that are not assigned to any groups.

        Returns
        -------
        list of str
            A list of unused playlist names.
        """
        all_playlist = self.get_playlist_names()
        used = {obj[0] for _, lst in self.get_groups_playlists().items() for obj in lst}
        for player in self.get_player_objects():  # additional playlists of a player belong to no group
            used.update(player.get("playlists") or [])
        for playlist in self._make_request("get", "/playlists").get("data", []):  # a playlist in a zone of another
            used.update(zone_references(playlist))
        return [name for name in all_playlist if name not in used]

    def delete_group(self, name: str):
        group_id = self.get_group_id_by_name(name)
        return self._make_request("delete", f"/groups/{group_id}")

    def delete_playlist(self, name: str):
        response = self._make_request("delete", f"/files/{path_segment(f'__{name}.json')}")
        request_body = {
            "playlist": name,
            "assets": []
        }
        _ = self._make_request("post", "/playlistfiles", json=request_body)
        return response

    def get_all_assets(self) -> List[str]:
        """
        Retrieves all asset names.

        Returns
        -------
        list of str
            A list of all asset names.
        """
        response = self._make_request("get", "/files")
        return [asset.get("name", "") for asset in response.get("data", {}).get("dbdata", [])]

    def get_used_assets(self) -> List[str]:
        """
        Retrieves the names of assets used in any playlists.

        Returns
        -------
        list of str
            A list of used asset names.
        """
        response = self._make_request("get", "/playlists")
        used_assets = []
        for playlist in response.get("data", []):
            used_assets.extend(asset.get("filename", "") for asset in playlist.get("assets", []))
            used_assets.extend(zone_references(playlist))
        for group in self._make_request("get", "/groups").get("data", []):
            if group.get("logo"):
                used_assets.append(group["logo"])
        return used_assets

    def get_unused_assets(self) -> List[str]:
        """
        Fetches assets that are not assigned to any playlists.

        Returns
        -------
        list of str
            A list of unused asset names.
        """
        all_assets = self.get_all_assets()
        used_assets = self.get_used_assets()
        unused_assets = [asset for asset in all_assets if asset not in used_assets]
        return unused_assets

    def delete_asset(self, name: str):
        return self._make_request("delete", f"/files/{path_segment(name)}")

    def get_assets_details(self) -> List[Dict[str, Any]]:
        """
        Retrieves detailed information about all uploaded assets.

        Returns
        -------
        list of dict
            A list of dictionaries, each containing details about an asset.
        """
        response = self._make_request("get", "/files")
        assets_details = []

        for asset in response["data"]["dbdata"]:
            asset_details = {
                "name": asset["name"],
                "type": asset.get("type", None),
                "duration": asset.get("duration", None),
                "size": asset.get("size", None),
                "thumbnail": asset.get("thumbnail", None),
                "validity": {
                    "enable": asset.get("validity", {}).get("enable", False),
                    "startdate": asset.get("validity", {}).get("startdate", ""),
                    "enddate": asset.get("validity", {}).get("enddate", ""),
                    "starthour": asset.get("validity", {}).get("starthour", ""),
                    "endhour": asset.get("validity", {}).get("endhour", "")
                },
                "groupIds": asset.get("groupIds", []),
                "playlists": asset.get("playlists", []),
                "labels": asset.get("labels", []),
                "resolution": {
                    "width": asset.get("resolution", {}).get("width", ""),
                    "height": asset.get("resolution", {}).get("height", "")
                }
            }
            assets_details.append(asset_details)

        return assets_details

    def get_player_details_overview(self) -> List[Dict[str, Any]]:
        """
        Retrieves an overview of player details including player name,
        group, version, IP, last report, location, and temperature.

        Returns
        -------
        list of dict
            A list of dictionaries containing player details.
        """
        player_details = []
        for obj in self.get_player_objects():
            player_details.append({
                "name": obj.get("name", ""),
                "group": (obj.get("group") or {}).get("name", ""),
                "version": obj.get("version", ""),
                "ip": obj.get("ip", ""),
                "last_report": obj.get("lastReported", ""),
                "location": obj.get("configLocation", ""),
                "notes": obj.get("notes", ""),
                "temperature": (obj.get("piTemperature") or "").strip(),
                "current_playlist": obj.get("currentPlaylist", ""),
                "labels": obj.get("labels", [])
            })
        return player_details

    def get_player_objects(self) -> List[Dict[str, Any]]:
        """
        All players of the account exactly as the server returns them: the one place that reads /players.

        The server numbers the pages from 0, and its "pages" field says nothing about how many there are (it is 1
        for every page that has players), so that field is not used: pages are read until one brings no player
        that is new, which also ends the loop for a server that ignores the page number.
        """
        players = []
        seen = set()
        for page in range(MAX_PLAYER_PAGES):
            params = {"page": page, "per_page": PLAYERS_PER_PAGE}
            objects = self._make_request("get", "/players", params=params).get("data", {}).get("objects", [])
            new = [obj for obj in objects if player_key(obj) not in seen]
            if not new:
                break
            seen.update(player_key(obj) for obj in new)
            players += new
        return players

    def get_all_players(self) -> Dict[str, Dict[str, Union[str, bool, List[str], Dict[str, str]]]]:
        """
        Retrieves all players and returns their details in a dictionary keyed by player name.

        Returns
        -------
        dict
            A dictionary where keys are player names and values are dictionaries containing player details.
        """
        players = {}
        for obj in self.get_player_objects():
            player_data = {
                "TZ": obj.get("TZ", ""),
                "cpuSerialNumber": obj.get("cpuSerialNumber", ""),
                "managed": obj.get("managed", True),
                "configLocation": obj.get("configLocation", ""),
                "labels": obj.get("labels", []),
                "group": {
                    "_id": obj["group"].get("_id", "") if obj.get("group") else "",
                    "name": obj["group"].get("name", "") if obj.get("group") else "default"
                },
                "_id": obj.get("_id", ""),
                "selfGroupId": obj.get("selfGroupId", ""),
                "version": obj.get("version", ""),
                "platform_version": obj.get("platform_version", ""),
                "myIpAddress": obj.get("myIpAddress", ""),
                "ip": obj.get("ip", ""),
                "location": obj.get("location", ""),
                "playlistOn": obj.get("playlistOn", False),
                "cecTvStatus": obj.get("cecTvStatus", False),
                "tvStatus": obj.get("tvStatus", False),
                "syncInProgress": obj.get("syncInProgress", False),
                "currentPlaylist": obj.get("currentPlaylist", ""),
                "licensed": obj.get("licensed", True),
                "installation": obj.get("installation", ""),
                "lastUpload": obj.get("lastUpload", 0),
                "lastReported": obj.get("lastReported", 0),
                "notes": obj.get("notes", "")
            }
            players[obj["name"]] = player_data

        return players

    def set_player_details(self, player_name: str, details: Dict[str, Any]) -> Dict[str, Any]:
        """
        Updates information about the specified player.

        Parameters
        ----------
        player_name : str
            The name of the player to update.
        details : dict
            A dictionary containing the player details to be updated.

        Returns
        -------
        json
            The response from the server.
        """
        player_id = self.get_player_id_by_name(player_name)
        return self._make_request("post", f"/players/{player_id}", json=details)

    def get_not_playing_players(self):
        return [obj.get("name", "") for obj in self.get_player_objects() if not obj.get("tvStatus")]

    def get_unused_labels(self):
        all_labels = self.get_labels()
        player_labels = flatten([label for _, label in self.get_player_labels()])
        group_labels = flatten([label for _, label in self.get_group_labels()])
        asset_labels = flatten([label for _, label in self.get_assets_labels()])
        playlist_labels = flatten([playlist.get("labels") or []
                                   for playlist in self._make_request("get", "/playlists").get("data", [])])
        location_labels = flatten([location.get("labels") or []
                                   for location in self._make_request("get", "/locations").get("data", [])])
        used = set(flatten([player_labels, group_labels, asset_labels, playlist_labels, location_labels]))
        return [label for label in all_labels if label not in used]

    def delete_label(self, name: str):
        label_id = self.get_label_id_by_name(name)
        return self._make_request("delete", f"/labels/{label_id}")

    def get_unused_locations(self):
        all_location = [list(loc.keys())[0] for loc in self.get_locations()]
        used_locations = {loc for _, loc in self.get_player_locations()}
        return [loc for loc in all_location if loc not in used_locations]

    def delete_location(self, name: str):
        location_id = self.get_location_id_by_name(name)
        return self._make_request("delete", f"/locations/{location_id}")

    def get_playlists_settings(self) -> (str, Optional[int]):
        response = self._make_request("get", "/playlists")
        return [
            (playlist.get("name", ""), playlist.get("settings", {}).get("domination", {}).get("timeInterval", None)) 
            for playlist in response.get("data", [])
        ]

    def set_playlist_settings(self, name: str, domination_interval: str):
        """
        Switches the domination of a playlist on with the interval, or off when the interval is empty. The other
        settings of the playlist (ads, audio, ticker) are sent back as it has them: the server takes the settings
        object exactly as sent, so writing the domination alone dropped all of them.
        """
        path = f"/playlists/{path_segment(name)}"
        settings = dict((self._make_request("get", path).get("data") or {}).get("settings") or {})
        if domination_interval:
            settings["domination"] = {**(settings.get("domination") or {}), "enable": True,
                                      "timeInterval": int(domination_interval)}
        else:
            settings["domination"] = {"enable": False}
        return self._make_request("post", path, json={"settings": settings})

    def get_assets_validity(self) -> List[Tuple[str, str, str, str, str]]:
        """
        Retrieves all asset names along with their validity periods.

        Returns
        -------
        list of tuples
            A list of tuples where each tuple contains the asset name, start date, and end date.
        """
        response = self._make_request("get", "/files")
        assets_validity = []

        for asset in response.get("data", {}).get("dbdata", []):
            asset_name = asset.get("name", "")
            validity = asset.get("validity", {})
            start_date = validity.get("startdate", "")
            end_date = validity.get("enddate", "")
            start_hour = validity.get("starthour", "")
            end_hour = validity.get("endhour", "")
            assets_validity.append((asset_name, start_date, end_date, start_hour, end_hour))

        return assets_validity

    def set_asset_validity(self, asset_name: str,
                           start_date: Optional[str] = None,
                           end_date: Optional[str] = None,
                           start_hour: Optional[str] = None,
                           end_hour: Optional[str] = None) -> Dict[str, Any]:
        """
        Sets the validity period for the specified asset.

        Parameters
        ----------
        asset_name : str
            The name of the asset.
        start_date : Optional[str]
            The start date of the validity period in ISO 8601 format.
        end_date : Optional[str]
            The end date of the validity period in ISO 8601 format.
        start_hour : Optional[int]
            The start hour of the validity period, 0-23 (a number: the server refuses a text).
        end_hour : Optional[int]
            The end hour of the validity period, 1-24.

        Returns
        -------
        json
            The response from the server.
        """
        asset_id = self.get_asset_id_by_name(asset_name)
        validity = {
            "enable": False
        }

        if start_date or end_date:
            validity["enable"] = True
            if start_date:
                validity["startdate"] = start_date
            if end_date:
                validity["enddate"] = end_date
            if start_hour is not None:  # 0 is an hour too
                validity["starthour"] = start_hour
            if end_hour is not None:
                validity["endhour"] = end_hour

        request_body = {
            "dbdata": {
                "name": asset_name,
                "_id": asset_id,
                "validity": validity
            }
        }

        return self._make_request("post", f"/files/{path_segment(asset_name)}", json=request_body)

    def send_player_command(self, player_name: str, command: str):
        player_id = self.get_player_id_by_name(player_name)
        api_end_point = f"/pishell/{player_id}"
        request_body = {"cmd": command}
        return self._make_request("post", api_end_point, json=request_body)

    def is_player_online(self, player_id: str) -> bool:
        """The current state of one player (a small request, not the whole list of players)."""
        return bool(self._make_request("get", f"/players/{player_id}")["data"].get("isConnected"))

    def get_group_files(self, group_id: str) -> List[str]:
        """The files the group sends to its players (what the players are to have on their disks)."""
        return list(self.get_group_details(group_id).get("assets") or [])

    def list_player_files(self, player_id: str) -> List[str]:
        """
        The names of the files in the folder of the media on the player, read by a fixed command that only lists them.

        Raises
        ------
        PlayerCommandError
            The player did not answer in time ("no_answer") or answered with an error ("failed").
        """
        try:
            answer = self._make_request("post", f"/pishell/{player_id}", json={"cmd": PLAYER_FILES_COMMAND},
                                        timeout=PLAYER_COMMAND_TIMEOUT)["data"]
        except requests.exceptions.Timeout:
            raise PlayerCommandError("no_answer")
        # A player that does not answer is a successful request with `err` set
        if answer.get("err"):
            raise PlayerCommandError("no_answer")
        if answer.get("stderr") and not answer.get("stdout"):
            raise PlayerCommandError("failed")
        return [line for line in (answer.get("stdout") or "").splitlines() if line]

    def take_player_snapshot(self, player_name: str) -> Dict[str, Any]:
        """
        Asks the player for a screenshot of what it is playing right now.

        Returns
        -------
        dict
            `url` of the image on the server and the time it was taken (`lastTaken`).
        """
        return self.take_snapshot(self.get_player_id_by_name(player_name))

    def take_snapshot(self, player_id: str) -> Dict[str, Any]:
        """Like `take_player_snapshot`, for a player whose id is already known (no lookup of the name)."""
        return self._make_request("post", f"/snapshot/{player_id}", timeout=SNAPSHOT_TIMEOUT)["data"]

    def download_snapshot(self, image_url: str) -> Tuple[bytes, str]:
        """
        Downloads the snapshot image and returns its bytes with the file extension.

        The address comes from the server's answer, so it is checked before it is followed: https only, and the
        session token is sent only to the server's own host, never to another one.

        Raises
        ------
        SnapshotError
            The address is unusable, the download failed, or the response is not an image or is too large.
        """
        server = urlparse(self._url)
        address = urljoin(f"{server.scheme}://{server.netloc}/", str(image_url))
        target = urlparse(address)
        if target.scheme != "https" or not target.hostname:
            raise SnapshotError("bad_url")

        try:
            # The token goes only to the server's own origin: the same host name on another port is another service
            if (target.hostname, target.port or 443) == (server.hostname, server.port or 443):
                response = self._request("get", address, headers={TOKEN_HEADER: self._session_token},
                                         timeout=SNAPSHOT_TIMEOUT, stream=True)
            else:
                response = requests.get(address, timeout=SNAPSHOT_TIMEOUT, stream=True)
            with response:
                if not response.ok:
                    raise SnapshotError("download")
                declared = response.headers.get("Content-Length", "")
                if declared.isdigit() and int(declared) > SNAPSHOT_MAX_BYTES:
                    raise SnapshotError("too_large")
                content = bytearray()
                for chunk in response.iter_content(chunk_size=65536):  # not all of it into memory before the check
                    content += chunk
                    if len(content) > SNAPSHOT_MAX_BYTES:
                        raise SnapshotError("too_large")
        except requests.exceptions.RequestException:
            raise SnapshotError("download")
        content = bytes(content)
        for signature, extension in IMAGE_SIGNATURES:
            if content.startswith(signature):
                return content, extension
        raise SnapshotError("not_image")

    def get_players_by_name(self, name: str):
        request_body = {
            "string": name
        }
        response = self._make_request("get", f"/players", json=request_body)
        return response.get("data", {}).get("objects", [])

    def get_groups_by_name(self, name: str):
        request_body = {
            "string": name
        }
        response = self._make_request("get", f"/groups", json=request_body)
        return response.get("data", {}).get("objects", [])

    def get_labels_by_name(self, name: str):
        response = self._make_request("get", f"/labels")
        return [item for item in response.get("data", []) if name in item.get("name", "")]

    def get_locations_by_name(self, name: str):
        response = self._make_request("get", f"/locations")
        return [item for item in response.get("data", []) if name in item.get("configLocation", "")]

    def remove_playlists_from_groups(self, playlists_to_remove: List[str]) -> Dict[str, List[str]]:
        """
        Odstraní zadané playlisty ze všech skupin.

        Parameters
        ----------
        playlists_to_remove : List[str]
            Seznam názvů playlistů, které mají být odstraněny.
 
        Returns
        -------
        Dict[str, List[str]]
            Slovník, kde klíčem je název skupiny a hodnotou seznam odstraněných playlistů.
        """
        if isinstance(playlists_to_remove, str):
            raise TypeError("playlists_to_remove must be a list of names: a single string would match substrings")
        names_to_remove = set(playlists_to_remove)
        removed_playlists = {}

        for group in self._make_request("get", "/groups").get("data", []):
            kept = [playlist for playlist in group.get("playlists", []) if playlist.get("name", "") not in names_to_remove]
            removed = [playlist.get("name", "") for playlist in group.get("playlists", [])
                       if playlist.get("name", "") in names_to_remove]
            if removed:
                self._set_group_playlists(group["_id"], group.get("name", ""), kept, group)  # the others as they are
                removed_playlists[group.get("name", "")] = removed

        return removed_playlists


def main():
    with open("./api_testing/login.json", "r") as login_file:
        credentials = json.loads(login_file.read())
    with (ServerApi(**credentials) as s):
        p = s.remove_expired_playlists_from_group("01 Test_MBIT")


if __name__ == "__main__":
    main()
