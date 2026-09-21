from typing import List, Tuple
from urllib.parse import urlparse


class AccountError(ValueError):
    """Invalid user input; `key` is the messages.json key of the text to show."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def normalize_url(raw: str) -> str:
    """
    Accepts only plain https addresses: the account credentials are sent to this URL, so plain http,
    embedded user info, query strings and fragments are rejected.
    """
    url = raw.strip().rstrip("/")
    parsed = urlparse(url)
    if (parsed.scheme != "https" or not parsed.hostname or "@" in parsed.netloc
            or parsed.query or parsed.fragment or any(char.isspace() for char in url)):
        raise AccountError("url_invalid")
    return url


def add_account(data: dict, name: str, url: str) -> str:
    """Adds a customer account to the config `data`; returns the stored name."""
    name = name.strip()
    if not name:
        raise AccountError("account_name_required")
    if name in data["logins"]:
        raise AccountError("account_exists")
    data["logins"][name] = {"url": normalize_url(url), "names": {}}
    return name


def add_login(data: dict, account: str, login: str) -> str:
    """Adds a login (passwords are kept in the OS credential store, not here); returns the stored name."""
    login = login.strip()
    if not login:
        raise AccountError("login_required")
    names = data["logins"][account].setdefault("names", {})
    if login in names:
        raise AccountError("login_exists")
    names[login] = {"login": login}
    return login


Credential = Tuple[str, str]  # (account URL, login): the key the password is stored under


def remember_selection(data: dict, account: str, login: str) -> bool:
    """
    Records the last used account (the config's `default`) and the last used login of that account.
    Returns True when `data` changed and has to be saved.
    """
    entry = data["logins"][account]
    before = (data.get("default"), entry.get("last"))
    if login in entry.get("names", {}):
        entry["last"] = login
    data["default"] = [account, entry.get("last", "")]
    return before != (data["default"], entry.get("last"))


def _unused(data: dict, candidates: List[Credential]) -> List[Credential]:
    """Passwords are shared by every entry with the same URL and login, so only unreferenced ones may go."""
    used = {(entry.get("url", ""), name["login"])
            for entry in data["logins"].values() for name in entry.get("names", {}).values()}
    return sorted(set(candidates) - used)


def remove_login(data: dict, account: str, name: str) -> List[Credential]:
    """Removes a login; returns the stored credentials that no remaining entry uses any more."""
    entry = data["logins"][account]
    removed = entry["names"].pop(name)
    if entry.get("last") == name:
        del entry["last"]
    if data.get("default") == [account, name]:
        data["default"] = [account, ""]
    return _unused(data, [(entry.get("url", ""), removed["login"])])


def remove_account(data: dict, account: str) -> List[Credential]:
    """Removes an account with all its logins; returns the stored credentials that are no longer used."""
    entry = data["logins"].pop(account)
    if data.get("default", ["", ""])[0] == account:
        data["default"] = ["", ""]
    return _unused(data, [(entry.get("url", ""), name["login"]) for name in entry.get("names", {}).values()])


def player_columns(data: dict, account: str) -> dict:
    """The column widths (pixels by column key) the user set in the player table of this account."""
    return dict(data["logins"].get(account, {}).get("player_columns", {}))


def set_player_columns(data: dict, account: str, widths: dict) -> None:
    """Stores the column widths of the account; nothing (or an empty dict) goes back to the defaults."""
    entry = data["logins"][account]
    if widths:
        entry["player_columns"] = dict(widths)
    else:
        entry.pop("player_columns", None)


# Optional columns of the player table that are switched off until the user switches them on. An account that has
# never made a choice about them (also one saved before they existed) has them off.
DEFAULT_HIDDEN_COLUMNS = ("temperature", "version")


def hidden_player_columns(data: dict, account: str) -> list:
    """The optional columns of the player table that are off for this account, the defaults included."""
    entry = data["logins"].get(account, {})
    hidden = set(entry.get("player_hidden", []))
    hidden |= set(DEFAULT_HIDDEN_COLUMNS) - set(entry.get("player_shown", []))
    return sorted(hidden)


def set_hidden_player_columns(data: dict, account: str, hidden: list) -> None:
    """
    Stores which columns are off. What is remembered is the difference from the defaults: the columns that are off
    although they are on by default, and the ones that are on although they are off by default.
    """
    entry = data["logins"][account]
    off = [column for column in hidden if column not in DEFAULT_HIDDEN_COLUMNS]
    on = [column for column in DEFAULT_HIDDEN_COLUMNS if column not in hidden]
    for key, value in (("player_hidden", off), ("player_shown", on)):
        if value:
            entry[key] = list(value)
        else:
            entry.pop(key, None)


def snapshot_window_size(data: dict, account: str):
    """The size (width, height) the user gave the snapshot windows of this account, or None."""
    return data["logins"].get(account, {}).get("snapshot_window")


def set_snapshot_window_size(data: dict, account: str, size) -> None:
    """Stores the size of the snapshot windows of the account; None goes back to the default."""
    entry = data["logins"][account]
    if size is None:
        entry.pop("snapshot_window", None)
    else:
        entry["snapshot_window"] = [int(size[0]), int(size[1])]


def player_window_geometry(data: dict, account: str):
    """The size and position (width, height, x, y) the user gave the player table window of this account, or None."""
    return data["logins"].get(account, {}).get("player_window")


def set_player_window_geometry(data: dict, account: str, geometry) -> None:
    """Stores the size and position of the account's player table window; None goes back to the default."""
    entry = data["logins"][account]
    if geometry is None:
        entry.pop("player_window", None)
    else:
        entry["player_window"] = [int(value) for value in geometry]


def player_font_size(data: dict, account: str):
    """The font size the user chose for the player table of this account, or None."""
    return data["logins"].get(account, {}).get("player_font")


def set_player_font_size(data: dict, account: str, size) -> None:
    """Stores the font size of the account's player table; None goes back to the default."""
    entry = data["logins"][account]
    if size is None:
        entry.pop("player_font", None)
    else:
        entry["player_font"] = int(size)
