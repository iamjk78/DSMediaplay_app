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
