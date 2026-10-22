import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import keyring
from keyring.backend import KeyringBackend
from keyring.errors import KeyringError

from tests.accounts_test import empty_config
from util import credentials
from util.legacy_import import merge_legacy_accounts, read_legacy_accounts
from util.paths import legacy_login_file

LEGACY = {
    "default": ["Old customer", "alice"],
    "logins": {
        "Old customer": {
            "url": "https://old.signage.dsmediaplay.com",
            "names": {
                "alice": {"login": "alice", "password": "s3cret"},
                "bob": {"login": "bob", "password": ""},
            },
        },
        "Bad url": {"url": "not a url", "names": {"carl": {"login": "carl", "password": "x"}}},
    },
}


class LegacyLoginFileTest(unittest.TestCase):
    def test_appdata_gives_the_path_the_old_app_used(self):
        with patch.dict(os.environ, {"APPDATA": r"C:\Users\jane\AppData\Roaming"}):
            self.assertEqual(legacy_login_file(), Path(r"C:\Users\jane\AppData\Roaming") / "dsmediaplay" / "login.json")

    def test_none_without_appdata(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(legacy_login_file())


class ReadLegacyAccountsTest(unittest.TestCase):
    def write(self, directory, content: str) -> Path:
        path = Path(directory) / "login.json"
        path.write_text(content, encoding="utf-8")
        return path

    def test_none_path_is_nothing_to_import(self):
        self.assertIsNone(read_legacy_accounts(None))

    def test_a_missing_file_is_nothing_to_import(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(read_legacy_accounts(Path(directory) / "nope.json"))

    def test_a_readable_file_is_parsed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(directory, json.dumps(LEGACY))
            self.assertEqual(read_legacy_accounts(path), LEGACY)

    def test_broken_json_is_nothing_to_import(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(directory, "{not json")
            self.assertIsNone(read_legacy_accounts(path))

    def test_the_wrong_shape_is_nothing_to_import(self):
        with tempfile.TemporaryDirectory() as directory:
            for content in ("[]", "42", '{"no_logins_key": true}', '{"logins": "not a dict"}'):
                with self.subTest(content=content):
                    path = self.write(directory, content)
                    self.assertIsNone(read_legacy_accounts(path))

    def test_a_file_that_cannot_be_read_is_nothing_to_import(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)  # a directory where a file is expected: OSError on open()
            self.assertIsNone(read_legacy_accounts(path))


class MergeLegacyAccountsTest(unittest.TestCase):
    def test_a_new_account_is_added_whole_with_its_password_still_plaintext(self):
        data = empty_config()

        changed = merge_legacy_accounts(data, copy.deepcopy(LEGACY))

        self.assertTrue(changed)
        account = data["logins"]["Old customer"]
        self.assertEqual(account["url"], "https://old.signage.dsmediaplay.com")
        self.assertEqual(account["names"]["alice"], {"login": "alice", "password": "s3cret"})
        self.assertEqual(account["names"]["bob"], {"login": "bob"})  # an empty password is not stored at all

    def test_an_account_whose_url_does_not_pass_validation_is_skipped_entirely(self):
        data = empty_config()

        merge_legacy_accounts(data, copy.deepcopy(LEGACY))

        self.assertNotIn("Bad url", data["logins"])

    def test_an_existing_account_keeps_its_own_url_and_only_gains_new_logins(self):
        data = empty_config()
        data["logins"]["Old customer"] = {"url": "https://kept.example.com", "names": {}}

        changed = merge_legacy_accounts(data, copy.deepcopy(LEGACY))

        self.assertTrue(changed)
        self.assertEqual(data["logins"]["Old customer"]["url"], "https://kept.example.com")
        self.assertEqual(data["logins"]["Old customer"]["names"]["alice"], {"login": "alice", "password": "s3cret"})

    def test_an_existing_login_is_left_exactly_as_it_is(self):
        data = empty_config()
        data["logins"]["Old customer"] = {"url": "https://kept.example.com",
                                          "names": {"alice": {"login": "alice"}}}  # no password on file

        merge_legacy_accounts(data, copy.deepcopy(LEGACY))

        self.assertEqual(data["logins"]["Old customer"]["names"]["alice"], {"login": "alice"})

    def test_the_real_login_field_is_used_even_if_it_differs_from_the_dictionary_key(self):
        # Not something this app's own "add login" dialog can produce (it always keeps the two the same), but the
        # old app's file is trusted at face value: the "login" field is what is actually sent to the server.
        data = empty_config()
        legacy = {"logins": {"Old customer": {"url": "https://old.signage.dsmediaplay.com",
                                              "names": {"Alice Assistant": {"login": "alice", "password": "s3cret"}}}}}

        merge_legacy_accounts(data, legacy)

        names = data["logins"]["Old customer"]["names"]
        self.assertNotIn("Alice Assistant", names)
        self.assertEqual(names["alice"], {"login": "alice", "password": "s3cret"})

    def test_a_login_without_a_usable_login_field_is_skipped(self):
        data = empty_config()
        legacy = {"logins": {"Old customer": {"url": "https://old.signage.dsmediaplay.com",
                                              "names": {"a": {"password": "x"}, "b": {"login": "", "password": "y"},
                                                       "c": {"login": "  ", "password": "z"}}}}}

        changed = merge_legacy_accounts(data, legacy)

        self.assertTrue(changed)  # the account itself is still added
        self.assertEqual(data["logins"]["Old customer"]["names"], {})

    def test_nothing_new_reports_no_change(self):
        data = empty_config()
        merge_legacy_accounts(data, copy.deepcopy(LEGACY))

        changed_again = merge_legacy_accounts(data, copy.deepcopy(LEGACY))

        self.assertFalse(changed_again)

    def test_malformed_entries_are_skipped_without_raising(self):
        data = empty_config()
        broken = {"logins": {"A": "not a dict", "B": {"url": "https://b.example.com", "names": "not a dict"},
                             "C": {"url": "https://c.example.com", "names": {"x": "not a dict"}}}}

        changed = merge_legacy_accounts(data, broken)

        self.assertTrue(changed)  # "B" and "C" are still added as accounts, just without any logins
        self.assertNotIn("A", data["logins"])
        self.assertEqual(data["logins"]["B"]["names"], {})
        self.assertEqual(data["logins"]["C"]["names"], {})

    def test_an_empty_legacy_file_changes_nothing(self):
        data = empty_config()

        self.assertFalse(merge_legacy_accounts(data, {"logins": {}}))
        self.assertEqual(data["logins"], {})


class InMemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        del self.store[(service, username)]


class ImportedThroughTheAppTest(unittest.TestCase):
    """The whole path: the app finds the old file, imports it and moves the passwords into the credential store."""

    def setUp(self):
        self.previous_keyring = keyring.get_keyring()
        keyring.set_keyring(InMemoryKeyring())
        self.addCleanup(keyring.set_keyring, self.previous_keyring)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config_path = os.path.join(self.directory.name, "logins.json")
        with open(self.config_path, "w", encoding="utf-8") as file:
            json.dump({"lang": "cz", "font": ["Helvetica", 12], "default": ["", ""], "logins": {}}, file)
        self.legacy_path = Path(self.directory.name) / "legacy.json"
        with open(self.legacy_path, "w", encoding="utf-8") as file:
            json.dump(LEGACY, file)

    def start_app(self):
        from gui_app import gui
        try:
            app = gui.DSMediaplayApp(self.config_path)
        except __import__("tkinter").TclError:
            self.skipTest("no display available")
        self.addCleanup(app.destroy)
        return app

    def test_the_account_the_password_and_the_done_flag_land_in_the_saved_config(self):
        with patch("gui_app.gui.legacy_login_file", return_value=self.legacy_path):
            self.start_app()

        with open(self.config_path, encoding="utf-8") as file:
            saved = json.load(file)
        self.assertTrue(saved["legacy_import_done"])
        self.assertEqual(saved["logins"]["Old customer"]["url"], "https://old.signage.dsmediaplay.com")
        self.assertNotIn("password", saved["logins"]["Old customer"]["names"]["alice"])  # moved out
        self.assertEqual(credentials.get_password("https://old.signage.dsmediaplay.com", "alice"), "s3cret")

    def test_a_second_start_does_not_reimport_something_the_user_removed(self):
        # A real second start would be a second, separate process; here the same window is simply told to load
        # what a fresh start would find on disk, and asked to import again, exactly as `run.py` does at startup.
        with patch("gui_app.gui.legacy_login_file", return_value=self.legacy_path):
            app = self.start_app()
        with open(self.config_path, encoding="utf-8") as file:
            data = json.load(file)
        del data["logins"]["Old customer"]  # the user removed the imported account again
        with open(self.config_path, "w", encoding="utf-8") as file:
            json.dump(data, file)

        app.all_data = app.load_account_configs()
        with patch("gui_app.gui.legacy_login_file", return_value=self.legacy_path):
            app.import_legacy_accounts()

        with open(self.config_path, encoding="utf-8") as file:
            self.assertNotIn("Old customer", json.load(file)["logins"])

    def test_no_old_file_still_sets_the_flag_so_it_is_only_checked_once(self):
        with patch("gui_app.gui.legacy_login_file", return_value=Path(self.directory.name) / "nope.json"):
            self.start_app()

        with open(self.config_path, encoding="utf-8") as file:
            saved = json.load(file)
        self.assertTrue(saved["legacy_import_done"])
        self.assertEqual(saved["logins"], {})

    def test_a_keyring_failure_leaves_the_flag_unset_so_it_is_retried(self):
        class FailingKeyring(InMemoryKeyring):
            def set_password(self, service, username, password):
                raise KeyringError("no backend")
        keyring.set_keyring(FailingKeyring())

        with patch("gui_app.gui.legacy_login_file", return_value=self.legacy_path), \
                patch("gui_app.gui.messagebox.showwarning"):
            self.start_app()

        with open(self.config_path, encoding="utf-8") as file:
            saved = json.load(file)
        self.assertNotIn("legacy_import_done", saved)
        self.assertEqual(saved["logins"], {})  # nothing half-imported was written either

    def test_after_a_keyring_failure_no_password_waits_in_memory_for_the_next_save(self):
        class FailingKeyring(InMemoryKeyring):
            def set_password(self, service, username, password):
                raise KeyringError("no backend")
        keyring.set_keyring(FailingKeyring())

        with patch("gui_app.gui.legacy_login_file", return_value=self.legacy_path), \
                patch("gui_app.gui.messagebox.showwarning"):
            app = self.start_app()
        app.all_data["font"] = ["Courier", 14]
        app.save_account_configs()  # any later save of the config, for any other reason

        with open(self.config_path, encoding="utf-8") as file:
            written = file.read()
        self.assertNotIn("s3cret", written)
        self.assertNotIn("Old customer", written)
        self.assertNotIn("legacy_import_done", written)


if __name__ == "__main__":
    unittest.main()
