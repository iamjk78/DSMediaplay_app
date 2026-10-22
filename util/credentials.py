import json
from datetime import datetime

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

__all__ = ["KeyringError", "get_password", "set_password", "delete_password", "migrate_plaintext_passwords",
          "migrate_per_account_items"]

SERVICE_NAME = "DSM_GUI"
# All accounts' passwords live under this one item (a JSON object of `_key(url, login)` to password), not one item
# per account: on macOS the credential store asks the user to allow access separately for every item, so this way
# it asks once for the whole application instead of once per customer account.
ACCOUNTS_ITEM = "accounts"


def _key(url: str, login: str) -> str:
    return f"{login}@{url}"


def _load_all(to_update: bool = False) -> dict:
    """
    The stored passwords, keyed by `_key(url, login)`. Raises KeyringError when the store is unavailable.

    Content that cannot be read (hand-edited, damaged) reads as nothing stored. To update it that would mean writing
    one password over all the others, so before the update starts from an empty list the content is kept under an
    item of its own (the store being unable to keep it stops the update).
    """
    raw = keyring.get_password(SERVICE_NAME, ACCOUNTS_ITEM)
    if not raw:
        return {}
    try:
        passwords = json.loads(raw)
    except ValueError:
        passwords = None
    if isinstance(passwords, dict):
        return passwords
    if to_update:
        keyring.set_password(SERVICE_NAME, f"{ACCOUNTS_ITEM}.unreadable-{datetime.now():%Y%m%d-%H%M%S}", raw)
    return {}


def _save_all(passwords: dict) -> None:
    keyring.set_password(SERVICE_NAME, ACCOUNTS_ITEM, json.dumps(passwords))


def get_password(url: str, login: str) -> str:
    """Returns the stored password, or an empty string when none is stored or no keyring is available."""
    try:
        return _load_all().get(_key(url, login)) or ""
    except KeyringError:
        return ""


def set_password(url: str, login: str, password: str) -> None:
    """Stores the password in the OS credential store. Raises KeyringError when it is unavailable."""
    passwords = _load_all(to_update=True)
    passwords[_key(url, login)] = password
    _save_all(passwords)


def delete_password(url: str, login: str) -> None:
    """Removes the stored password, if there is one. Raises KeyringError when the store is unavailable."""
    passwords = _load_all(to_update=True)
    if passwords.pop(_key(url, login), None) is not None:
        _save_all(passwords)


def migrate_plaintext_passwords(data: dict) -> bool:
    """
    Moves passwords found in a legacy account config into the OS credential store and removes them from `data`.

    Returns True when `data` was changed and has to be saved. The store is written to once, with every password
    collected first: a store that turns out to be unavailable (KeyringError) raises before `data` is touched at
    all, so nothing is ever dropped without being saved, and this can simply be tried again later.
    """
    changed_accounts = []  # every account dict that has a "password" field, whatever becomes of it
    new_passwords = {}  # of those, the ones worth keeping (a real password with a login to store it under)
    for administration in data.get("logins", {}).values():
        url = administration.get("url", "")
        for account in administration.get("names", {}).values():
            if "password" not in account:
                continue
            changed_accounts.append(account)
            if account["password"] and account.get("login"):
                new_passwords[_key(url, account["login"])] = account["password"]
    if not changed_accounts:
        return False
    if new_passwords:
        passwords = _load_all(to_update=True)
        passwords.update(new_passwords)
        _save_all(passwords)
    for account in changed_accounts:
        del account["password"]
    return True


def migrate_per_account_items(data: dict) -> bool:
    """
    Moves a password stored under an item of its own (the shape this app used before every account came to share
    one item) into the shared one, and removes the old item. `data` says which accounts to look for; one that
    never had a password of its own is simply not found and costs nothing more than the one lookup.

    Naturally never repeats itself: once an old item is moved, looking for it again finds nothing, so this can be
    called on every start without a "done" flag. Returns True when anything was moved. The shared item is written
    to once, with every password collected first, so it is never left half updated; an old item is only removed
    once its password is confirmed to be in the shared one.
    """
    found = {}
    for administration in data.get("logins", {}).values():
        url = administration.get("url", "")
        for account in administration.get("names", {}).values():
            login = account.get("login")
            if not login:
                continue
            try:
                old = keyring.get_password(SERVICE_NAME, _key(url, login))
            except KeyringError:
                old = None
            if old:
                found[_key(url, login)] = old
    if not found:
        return False
    passwords = _load_all(to_update=True)
    passwords.update(found)
    _save_all(passwords)
    for key in found:
        try:
            keyring.delete_password(SERVICE_NAME, key)
        except PasswordDeleteError:
            pass
    return True
