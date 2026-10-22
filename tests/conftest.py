import keyring
import pytest
from keyring.backend import KeyringBackend

import quiet_tk

quiet_tk.install()


class InMemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        self.store.pop((service, username), None)


@pytest.fixture(autouse=True)
def isolated_from_the_users_data(tmp_path, monkeypatch):
    """
    No test may read or write the passwords in the real credential store (macOS: the Keychain, which asks the person at
    the keyboard for permission) or the old app's accounts file. A test that wants its own backend sets one, as before.
    """
    previous = keyring.get_keyring()
    keyring.set_keyring(InMemoryKeyring())
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    yield
    keyring.set_keyring(previous)
