import keyring
from keyring.errors import KeyringError, PasswordDeleteError

__all__ = ["KeyringError", "get_password", "set_password", "delete_password", "migrate_plaintext_passwords"]

SERVICE_NAME = "DSM_GUI"


def _key(url: str, login: str) -> str:
    return f"{login}@{url}"


def get_password(url: str, login: str) -> str:
    """Returns the stored password, or an empty string when none is stored or no keyring is available."""
    try:
        return keyring.get_password(SERVICE_NAME, _key(url, login)) or ""
    except KeyringError:
        return ""


def set_password(url: str, login: str, password: str) -> None:
    """Stores the password in the OS credential store. Raises KeyringError when it is unavailable."""
    keyring.set_password(SERVICE_NAME, _key(url, login), password)


def delete_password(url: str, login: str) -> None:
    try:
        keyring.delete_password(SERVICE_NAME, _key(url, login))
    except PasswordDeleteError:
        pass


def migrate_plaintext_passwords(data: dict) -> bool:
    """
    Moves passwords found in a legacy account config into the OS credential store and removes them from `data`.

    Returns True when `data` was changed and has to be saved. Raises KeyringError before touching
    a password that could not be stored, so nothing is ever dropped without being saved first.
    """
    changed = False
    for administration in data.get("logins", {}).values():
        url = administration.get("url", "")
        for account in administration.get("names", {}).values():
            if "password" not in account:
                continue
            if account["password"] and account.get("login"):
                set_password(url, account["login"], account["password"])
            del account["password"]
            changed = True
    return changed
