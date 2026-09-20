from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple, Optional, Union
from urllib.parse import urljoin, urlparse
import requests
from requests.adapters import HTTPAdapter
import json
from dataclasses import dataclass

LOGIN_TIMEOUT = 30  # seconds; without it a network black hole would freeze the window forever
SNAPSHOT_TIMEOUT = 60  # seconds; the server asks the player for the screenshot and waits for it
SNAPSHOT_MAX_BYTES = 20 * 1024 * 1024
IMAGE_SIGNATURES = ((b"\x89PNG\r\n\x1a\n", ".png"), (b"\xff\xd8\xff", ".jpg"), (b"GIF8", ".gif"))

# The order of the days in the server's location schedule (`weekDays`, index 0 = Sunday), the way the web UI shows them
# (SU MO TU ... SA). Reading, writing, the CSV export and the input all use this one order.
WEEK_DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


class _AssertHostnameAdapter(HTTPAdapter):
    """Verifies the server certificate against `assert_hostname` instead of the host that is connected to."""

    def __init__(self, assert_hostname: str, **kwargs) -> None:
        self._assert_hostname = assert_hostname
        super().__init__(**kwargs)

    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, assert_hostname=self._assert_hostname, **kwargs)


def _assert_hostname_for(url: str) -> Optional[str]:
    """
    Wildcard certificates never match hostnames containing an underscore (e.g. shop_admin.signage...), although
    the server presents a valid certificate for them. The certificate chain is still verified; only the name
    check uses the hyphenated equivalent, which the wildcard covers.
    """
    host = urlparse(url).hostname or ""
    return host.replace("_", "-") if "_" in host else None


def flatten(xss: List[Any]):
    return [x for xs in xss for x in xs]


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


@dataclass
class ResponseError(ServerApiError):
    """
    Response returned non-200 code.

    Attributes
    ----------
    params : dict
        The parameters of the failed request.
    """
    params: dict


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


class ServerApi:
    def __init__(self, *, url: str, login: str, password: str) -> None:
        """
        Initializes the ServerApi with the given URL, login, and password.

        Parameters
        ----------
        url : str
            The base URL for the API.
        login : str
            The login username.
        password : str
            The password for API access.
        """
        self._url = url
        self._login = login
        self._password = password
        self._assert_hostname = _assert_hostname_for(url)
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
        Exits the runtime context related to this object.
        """
        self._close_session()

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

    def _make_request(self, method: str, endpoint: str, **kwargs) -> json:
        url = f"{self._url}{endpoint}"
        headers = {"Content-Type": "application/json"}
        kwargs.setdefault("headers", headers)
        kwargs.setdefault("params", {}).update({"token": self._session_token})
        response = self._request(method, url, **kwargs)

        if not response.ok:
            raise ResponseError(kwargs)
        response_json = response.json()
        if not response_json.get("success", False):
            raise ResponseError(kwargs)
        return response_json

    def get_player_names(self) -> List[str]:
        """
        Returns a list of player names.

        Returns
        -------
        list of str
            A list of player names.
        """
        response = self._make_request("get", "/players")
        return [obj.get("name", "") for obj in response.get("data", {}).get("objects", [])]

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
        response = self._make_request("get", "/players")
        return [obj.get("name", "") for obj in response.get("data", {}).get("objects", []) if not obj.get("playlistOn", True)]

    def get_disconnected_players(self) -> List[str]:
        """
        Returns a list of disconnected player names.

        Returns
        -------
        list of str
            A list of player names.
        """
        response = self._make_request("get", "/players")
        return [obj.get("name", "") for obj in response.get("data", {}).get("objects", []) if not obj.get("isConnected", None)]

    def get_online_players(self) -> List[str]:

        response = self._make_request("get", "/players")
        return [
            obj.get("name", "")
            for obj in response.get("data", {}).get("objects", [])
            if obj.get("isConnected", True) and obj.get("playlistOn", True)
        ]

    def get_players_for_deploy(self, group_names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Retrieves players (optionally filtered by a list of groups) with the fields needed
        to drive a sequential per-player deploy: id, group id/name and connection status.

        The first request is sent without page/per_page (same as every other call to
        /players in this module) so that servers which don't support those params keep
        working exactly as before. Additional pages are only requested if the response
        itself reports more than one page.

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
        page = 1
        while True:
            params = {"page": page} if page > 1 else {}
            response = self._make_request("get", "/players", params=params)
            data = response.get("data", {})
            for obj in data.get("objects", []):
                group = obj.get("group") or {}
                players.append({
                    "name": obj.get("name", ""),
                    "_id": obj.get("_id", ""),
                    "group_id": group.get("_id", ""),
                    "group_name": group.get("name", ""),
                    "isConnected": obj.get("isConnected", False)
                })
            if page >= data.get("pages", 1):
                break
            page += 1

        if group_names is not None:
            players = [player for player in players if player["group_name"] in group_names]

        return players

    def trigger_player_deploy(self, player_id: str, group_id: str, group_name: str) -> json:
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
        response = self._make_request("get", "/players")
        for obj in response.get("data", {}).get("objects", []):
            if name == obj.get("name", ""):
                return obj["_id"]
        filtered = [entity["_id"] for entity in response.get("data", []) if name == entity.get("name", "")]
        if len(filtered) == 1:
            return filtered[0]
        raise NameResolutionError(name)

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
        response = self._make_request("get", f"/files/{name}")
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
        response = self._make_request("get", "/labels", params={"string": name})
        if len(response.get("data", [])) == 1:
            return response["data"][0]["_id"]
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
        response = self._make_request("get", "/groups", params={"string": name})
        if len(response.get("data", [])) == 1:
            return response["data"][0]["_id"]
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

    def _set_group_playlists(self, group_id: str, group: str, playlists: List[Dict]) -> json:
        """
        Helper function to set playlists for a group.

        Parameters
        ----------
        group_id : str
            The unique ID of the group.
        group : str
            The name of the group.
        playlists : list of dict
            A list of playlist dictionaries.

        Returns
        -------
        json
            The response from the server.
        """
        request_body = {
            "_id": group_id,
            "name": group,
            "playAllEligiblePlaylists": "true",
            "playlists": playlists
        }
        return self._make_request("post", f"/groups/{group_id}", json=request_body)

    def set_playlist_to_group(self, group: str,
                              playlists: List[Tuple[str, Optional[str], Optional[str], Optional[str], Optional[str]]]) \
            -> json:
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
        group_playlists = [
            {
                "name": playlist_name,
                "settings": {
                    **({"durationEnable": "true", "startdate": start_date, "enddate": end_date}
                       if start_date and end_date else {}),
                    **({"timeEnable": "true", "starttime": start_time, "endtime": end_time}
                       if start_time and end_time else {})
                }
            }
            for playlist_name, start_date, end_date, start_time, end_time in playlists
        ]
        return self._set_group_playlists(group_id, group, group_playlists)

    def set_playlist_to_group_detailed(self, group: str,
                                       playlists: List[Tuple[str, Optional[str], Optional[str], Optional[List[int]], Optional[str], Optional[str]]]) -> json:
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
        group_playlists = []

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

            group_playlists.append(playlist)

        return self._set_group_playlists(group_id, group, group_playlists)

    def set_group_to_player(self, group: str, player: str) -> json:
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
        response = self._make_request("get", "/players")
        return [
            (obj.get("name", ""), obj.get("group", {}).get("name", "")) 
            for obj in response.get("data", {}).get("objects", [])
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
                for playlist in group["playlists"]
            ]
        return group_playlist_details

    def set_assets_to_playlist(self, playlist: str, assets: List[str]) -> json:
        """
        Updates the playlist with the specified assets and their durations.

        Parameters
        ----------
        playlist : str
            The name of the playlist.
        assets : list of tuples
            List of tuples where each tuple contains asset filename and duration.

        Returns
        -------
        json
            The response from the server.
        """
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
        return self._make_request("post", f"/playlists/{playlist}", json=settings_request_body)

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
        group_id = self.get_group_id_by_name(group)
        group_details = self.get_group_details(group_id)

        new_playlists = []
        removed = []

        for playlist in group_details.get("playlists", []):
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

    def set_player_note(self, player_name: str, note: str) -> json:
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
        response = self._make_request("get", "/players")
        return [(obj.get("name", ""), obj.get("configLocation", "ERROR")) for obj in response.get("data", {}).get("objects", [])]

    def set_player_config_location(self, player_name: str, config_location: str) -> json:
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
        response = self._make_request("get", "/players")
        return [(obj["name"], obj.get("notes", "")) for obj in response["data"]["objects"]]

    def get_labels(self) -> List[str]:
        """
        Retrieves all labels.

        Returns
        -------
        list of str
            A list of label names.
        """
        response = self._make_request("get", "/labels/")
        return [obj.get("name", "") for obj in response.get("data", [])]

    def get_additional_playlists(self) -> List[Tuple[str, List[str]]]:
        response = self._make_request("get", "/players")
        return [(obj.get("name", ""), obj.get("playlists", [])) for obj in response.get("data", {}).get("objects", [])]

    def set_player_additional_playlist(self, player_name: str, additional_playlists: List[str]) -> json:
        player_id = self.get_player_id_by_name(player_name)
        request_body = {"playlists": additional_playlists}

        return self._make_request("post", f"/players/{player_id}", json=request_body)

    def set_player_labels(self, player_name: str, labels: List[str]) -> json:
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
        response = self._make_request("get", "/players")
        return [(obj.get("name", ""), obj.get("labels", [])) for obj in response.get("data", {}).get("objects", [])]

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
            toggle_rows = location.get('toggleRows', False)
            times = {day: {"on": "", "off": ""} for day in WEEK_DAYS}

            for row in toggle_rows:
                on_time = row['turnOn']
                off_time = row['turnOff']
                for i, is_active in enumerate(row.get('weekDays', [])):
                    if is_active:
                        day = list(times.keys())[i]
                        times[day]["on"] = on_time
                        times[day]["off"] = off_time

            location_data = {location_name: times}
            locations_data.append(location_data)

        return locations_data

    def set_location(self, location_name: str, times: Dict[str, Dict[str, str]]) -> json:
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

    def rename_group(self, old_name: str, new_name: str) -> json:
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
        data = self._make_request("get", f"/players/").get("data", {}).get("objects", [])

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
                group.get("sleep", {}).get("ontime", None),
                group.get("sleep", {}).get("offtime", None),
                group.get("selectedVideoPlayer", None)
            )
            for group in response.get("data", [])
        ]
        return group_settings

    def set_group_settings(self, group: str, resolution: str, orientation: str, reboot_time: Optional[str],
                           deploy_everyday_time: Optional[str], combine_playlist: bool, all_eligible: bool,
                           on_time: Optional[str], off_time: Optional[str], video_player: Optional[str]) -> json:
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
            request_body.update({
                "reboot": {
                    "enable": True,
                    "time": reboot_time
                }
            })
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

        if on_time and on_time:
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

    def rename_location(self, old_name: str, new_name: str) -> json:
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

    def rename_player(self, old_name: str, new_name: str) -> json:
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

        for playlist in group_details.get("playlists", []):
            end_date = playlist.get("settings", {}).get("enddate")
            if end_date and end_date[:10] < current_date:
                removed.append(playlist["name"])
            else:
                new_playlists.append(playlist)

        if removed:
            group_details["playlists"] = new_playlists
            self.update_group_details(group_id, group_details)

        return removed

    def create_location(self, name: str) -> json:
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

    def create_group(self, name: str) -> json:
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

    def create_player(self, name: str) -> json:
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

        return self._make_request("post", "/players/", json=request_body)

    def create_playlist(self, name: str) -> json:
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

    def create_label(self, name: str) -> json:
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
        response = self._make_request("get", "/players")
        return [
            obj.get("name", "")
            for obj in response.get("data", {}).get("objects", []) if label_name in obj.get("labels", [])
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
        response = self._make_request("get", "/players/")
        return [(obj["name"], obj.get("version", "N/A")) for obj in response.get("data", {}).get("objects", [])]

    def player_update(self, name: str) -> json:
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
        group_playlists = self.get_groups_playlists()
        filter_playlist = [obj[0] for _, lst in group_playlists.items() for obj in lst]
        return list(filter(lambda x: x not in filter_playlist, all_playlist))

    def delete_group(self, name: str):
        group_id = self.get_group_id_by_name(name)
        return self._make_request("delete", f"/groups/{group_id}")

    def delete_playlist(self, name: str):
        response = self._make_request("delete", f"/files/__{name}.json")
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
        return self._make_request("delete", f"/files/{name}")

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
        response = self._make_request("get", "/players")
        player_details = []
        for obj in response["data"]["objects"]:
            player_details.append({
                "name": obj.get("name", ""),
                "group": obj.get("group", {}).get("name", ""),
                "version": obj.get("version", ""),
                "ip": obj.get("ip", ""),
                "last_report": obj.get("lastReported", ""),
                "location": obj.get("configLocation", ""),
                "notes": obj.get("notes", ""),
                "temperature": obj.get("piTemperature", "").strip(),
                "current_playlist": obj.get("currentPlaylist", ""),
                "labels": obj.get("labels", [])
            })
        return player_details

    def get_player_objects(self) -> List[Dict[str, Any]]:
        """All players of the account exactly as the server returns them, following its pages if there are several."""
        data = self._make_request("get", "/players").get("data", {})
        players = list(data.get("objects", []))
        for page in range(2, int(data.get("pages") or 1) + 1):
            data = self._make_request("get", "/players", params={"page": page}).get("data", {})
            players += data.get("objects", [])
        return players

    def get_all_players(self) -> Dict[str, Dict[str, Union[str, bool, List[str], Dict[str, str]]]]:
        """
        Retrieves all players and returns their details in a dictionary keyed by player name.

        Returns
        -------
        dict
            A dictionary where keys are player names and values are dictionaries containing player details.
        """
        response = self._make_request("get", "/players")

        players = {}
        for obj in response["data"]["objects"]:
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

    def set_player_details(self, player_name: str, details: Dict[str, Any]) -> json:
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
        response = self._make_request("get", "/players")
        return [obj.get("name", "") for obj in response.get("data", {}).get("objects", []) if not obj.get("tvStatus")]

    def get_unused_labels(self):
        all_labels = self.get_labels()
        player_labels = flatten([label for _, label in self.get_player_labels()])
        group_labels = flatten([label for _, label in self.get_group_labels()])
        asset_labels = flatten([label for _, label in self.get_assets_labels()])
        return list(filter(lambda x: x not in set(flatten([player_labels, group_labels, asset_labels])), all_labels))

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
        body = {
            "settings": {
                "domination": {
                    "enable": False
                }
            }
        }
        if domination_interval:
            num = int(domination_interval)
            body = {
                "settings": {
                    "domination": {
                        "enable": True,
                        "timeInterval": num
                    }
                }
            }
        return self._make_request("post", f"/playlists/{name}", json=body)

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
                           end_hour: Optional[str] = None) -> json:
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
        start_hour : Optional[str]
            The start hour of the validity period.
        end_hour : Optional[str]
            The end hour of the validity period.

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
            if start_hour:
                validity["starthour"] = start_hour
            if end_hour:
                validity["endhour"] = end_hour

        request_body = {
            "dbdata": {
                "name": asset_name,
                "_id": asset_id,
                "validity": validity
            }
        }

        return self._make_request("post", f"/files/{asset_name}", json=request_body)

    def send_player_command(self, player_name: str, command: str):
        player_id = self.get_player_id_by_name(player_name)
        api_end_point = f"/pishell/{player_id}"
        request_body = {"cmd": command}
        return self._make_request("post", api_end_point, json=request_body)

    def take_player_snapshot(self, player_name: str) -> Dict[str, Any]:
        """
        Asks the player for a screenshot of what it is playing right now.

        Returns
        -------
        dict
            `url` of the image on the server and the time it was taken (`lastTaken`).
        """
        player_id = self.get_player_id_by_name(player_name)
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
            if target.hostname == server.hostname:
                response = self._request("get", address, params={"token": self._session_token},
                                         timeout=SNAPSHOT_TIMEOUT)
            else:
                response = requests.get(address, timeout=SNAPSHOT_TIMEOUT)
        except requests.exceptions.RequestException:
            raise SnapshotError("download")
        if not response.ok:
            raise SnapshotError("download")
        content = response.content
        if len(content) > SNAPSHOT_MAX_BYTES:
            raise SnapshotError("too_large")
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
        removed_playlists = {}

        groups_playlists = self.get_groups_playlists_details()

        for group_name, playlists in groups_playlists.items():
            new_playlists = []
            removed = []

            for playlist in playlists:
                if playlist["playlist_name"] in playlists_to_remove:
                    removed.append(playlist["playlist_name"])
                else:
                    new_playlists.append(playlist)

            if removed:
                body = [(
                    playlist.get("playlist_name", ""), playlist.get("start_date", None),
                    playlist.get("end_date", None),
                    playlist.get("days_of_week", None),
                    playlist.get("start_time", None),
                    playlist.get("end_time", None)
                    ) for playlist in new_playlists]
                resp = self.set_playlist_to_group_detailed(group_name, body)
                removed_playlists[group_name] = removed

        return removed_playlists


def main():
    with open("./api_testing/login.json", "r") as login_file:
        credentials = json.loads(login_file.read())
    with (ServerApi(**credentials) as s):
        p = s.remove_expired_playlists_from_group("01 Test_MBIT")


if __name__ == "__main__":
    main()
