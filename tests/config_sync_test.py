import json
import os
import tempfile
import time
import tkinter as tk
import unittest

import keyring
from keyring.backend import KeyringBackend

from gui_app.gui import DSMediaplayApp


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        self.store.pop((service, username), None)


def account(url):
    return {"url": url, "names": {"a1": {"login": "a1"}}}


class ConfigSyncTest(unittest.TestCase):
    def setUp(self):
        self.previous_keyring = keyring.get_keyring()
        keyring.set_keyring(MemoryKeyring())
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, "logins.json")
        self.write({"lang": "cz", "font": ["Helvetica", 12], "default": ["", ""],
                    "logins": {"A": account("https://a.example.com")}})
        try:
            self.app = DSMediaplayApp(self.path)
        except tk.TclError:
            self.skipTest("no display available")
        self.app.update()

    def tearDown(self):
        if hasattr(self, "app"):
            self.app.destroy()
        keyring.set_keyring(self.previous_keyring)
        self.directory.cleanup()

    def write(self, data):
        with open(self.path, "w", encoding="utf-8") as file:
            json.dump(data, file)
        # A modification time that is certainly not the one of the write before, whatever the file system measures in
        self._modified = getattr(self, "_modified", 1_700_000_000_000_000_000) + 10 ** 9
        os.utime(self.path, ns=(self._modified, self._modified))

    def read(self):
        with open(self.path, encoding="utf-8") as file:
            return json.load(file)

    def edit_outside(self, name="Added outside", url="https://x.example.com"):
        data = self.read()
        data["logins"][name] = {"url": url, "names": {}}
        self.write(data)

    def select(self, account_name, login):
        self.app.option_choose_administration.set(account_name)
        self.app.on_account_selected()
        self.app.option_choose_name.set(login)
        self.app.on_login_selected()

    def test_reload_button_is_gone(self):
        self.assertFalse(hasattr(self.app, "reload_button"))

    def test_a_later_save_does_not_overwrite_changes_made_outside_the_app(self):
        self.edit_outside()

        self.select("A", "a1")  # remembering the selection saves the file

        self.assertEqual(set(self.read()["logins"]), {"A", "Added outside"})
        self.assertEqual(self.read()["default"], ["A", "a1"])

    def test_adding_an_account_keeps_changes_made_outside_the_app(self):
        self.edit_outside()

        self.app.add_account("Mine", "https://mine.example.com")

        self.assertEqual(set(self.read()["logins"]), {"A", "Added outside", "Mine"})

    def test_removing_a_login_keeps_changes_made_outside_the_app(self):
        self.select("A", "a1")
        self.edit_outside()
        self.app.option_choose_name.set("a1")

        import gui_app.gui as gui
        original, gui.messagebox.askyesno = gui.messagebox.askyesno, lambda *a, **k: True
        try:
            self.app.remove_login()
        finally:
            gui.messagebox.askyesno = original

        self.assertEqual(set(self.read()["logins"]), {"A", "Added outside"})
        self.assertEqual(self.read()["logins"]["A"]["names"], {})

    def test_window_focus_shows_outside_changes_and_keeps_the_selection(self):
        self.select("A", "a1")
        self.edit_outside()

        self.app.event_generate("<FocusIn>")
        self.app.update()

        self.assertIn("Added outside", self.app.option_choose_administration["values"])
        self.assertEqual((self.app.option_choose_administration.get(), self.app.option_choose_name.get()), ("A", "a1"))

    def test_selected_account_removed_outside_the_app_is_handled(self):
        self.select("A", "a1")
        data = self.read()
        data["logins"] = {"B": account("https://b.example.com")}
        self.write(data)

        self.app.option_choose_name.set("a1")
        self.app.on_login_selected()  # must neither crash nor bring the account back

        self.assertEqual(set(self.read()["logins"]), {"B"})
        self.assertEqual(self.app.option_choose_administration.get(), "")

    def test_own_writes_are_not_taken_for_outside_changes(self):
        self.app.add_account("Mine", "https://mine.example.com")

        self.assertFalse(self.app.sync_from_disk())

    def test_an_unreadable_file_is_ignored_instead_of_crashing(self):
        with open(self.path, "w", encoding="utf-8") as file:
            file.write("{ this is not json")

        self.assertFalse(self.app.sync_from_disk())
        self.assertIn("A", self.app.account_data)

    def test_saving_leaves_no_temporary_files_behind(self):
        self.app.add_account("Mine", "https://mine.example.com")

        self.assertEqual(os.listdir(self.directory.name), ["logins.json"])


if __name__ == "__main__":
    unittest.main()
