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
