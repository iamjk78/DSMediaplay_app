import gc
import tkinter as tk

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
def a_large_screen(monkeypatch):
    """
    The windows of the application size and place themselves by the screen. The tests expect a normal desktop; a runner
    of a build has a screen of 1024 x 768, which would shrink every window and fail the tests of the sizes.
    """
    for name, value in (("winfo_screenwidth", 2560), ("winfo_screenheight", 1440), ("winfo_vrootwidth", 2560),
                        ("winfo_vrootheight", 1440), ("winfo_vrootx", 0), ("winfo_vrooty", 0)):
        monkeypatch.setattr(tk.Misc, name, lambda self, value=value: value)


@pytest.fixture(autouse=True)
def windows_may_be_larger_than_the_screen(monkeypatch):
    """The system keeps a window within the screen (Tk's default largest size): on a small screen of a runner the
    windows would not get the sizes the tests ask for, whatever the application does."""
    for window_class in (tk.Tk, tk.Toplevel):
        def init(self, *args, _original=window_class.__init__, **kwargs):
            _original(self, *args, **kwargs)
            try:
                self.wm_maxsize(4000, 3000)
            except tk.TclError:
                pass
        monkeypatch.setattr(window_class, "__init__", init)


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
    # Tk variables and images are finalized by whichever thread happens to run the garbage collector; one that is not
    # the thread of the interpreter that made them aborts the whole process. So the garbage of a test goes here.
    gc.collect()


@pytest.fixture(autouse=True)
def no_real_call_to_github(monkeypatch):
    """
    The application looks for updates on GitHub, and a test that forgets to replace that would ask the real server (and
    show a real window with the answer). Every request to GitHub that gets this far is a mistake of the test.
    """
    import requests.sessions
    request = requests.sessions.Session.request

    def guarded(self, method, url, *args, **kwargs):
        if "github.com" in str(url):
            raise AssertionError(f"a test asked GitHub for real: {method} {url}")
        return request(self, method, url, *args, **kwargs)

    monkeypatch.setattr(requests.sessions.Session, "request", guarded)
