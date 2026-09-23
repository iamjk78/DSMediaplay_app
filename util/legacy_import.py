"""
A one-time import of the accounts, logins and passwords of the old, network-drive-launched version of this app
(see gui_app.gui.DSMediaplayApp.import_legacy_accounts for when this runs and how it is never retried).
"""
import json
from pathlib import Path
from typing import Any, Dict, Optional

from util.accounts import AccountError, add_account, add_login


def read_legacy_accounts(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    """
    The accounts of the old app, if `path` exists and reads as a config of the same shape. Never raises: a missing,
    unreadable or malformed file is treated the same as "nothing to import" (this runs at every startup until an
    import has happened, so it must never be the reason the application fails to start).
    """
    if path is None:
        return None
    try:
        with open(path, encoding="utf-8") as file:
            raw = json.load(file)
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) and isinstance(raw.get("logins"), dict) else None


def merge_legacy_accounts(data: dict, legacy: dict) -> bool:
    """
    Adds the accounts, logins and passwords of `legacy` that `data` does not have yet: an account already in `data`
    keeps its stored URL (only the logins it does not have yet are added to it); a login already there keeps
    whatever password it has. Nothing already in `data` is ever changed or removed.

    A password is added as a plaintext "password" field, the shape this app's own config used before passwords
    moved to the OS credential store: `DSMediaplayApp.migrate_plaintext_passwords` (already run at every startup)
    then moves it there the same way it already does for that shape, and removes it from the file again.

    Never raises: an account or a login that is not usable (a bad URL, a name already taken) is skipped on its own,
    the rest of `legacy` is still imported.

    Returns True when anything was added.
    """
    changed = False
    for account_name, account in legacy.get("logins", {}).items():
        if not isinstance(account, dict):
            continue
        if account_name not in data["logins"]:
            try:
                add_account(data, account_name, account.get("url", ""))
            except AccountError:
                continue
            changed = True
        names = account.get("names", {})
        if not isinstance(names, dict):
            continue
        existing_names = data["logins"][account_name].get("names") or {}
        for login in names.values():
            if not isinstance(login, dict):
                continue
            # The dict key is only ever a label; the "login" field is the real, actual credential (this app
            # always keeps the two the same when it adds a login itself, so the field is what has to be trusted).
            real_login = login.get("login")
            if not isinstance(real_login, str) or not real_login.strip() or real_login in existing_names:
                continue
            try:
                add_login(data, account_name, real_login)
            except AccountError:
                continue
            password = login.get("password")
            if password and isinstance(password, str):
                data["logins"][account_name]["names"][real_login]["password"] = password
            changed = True
    return changed
