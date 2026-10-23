import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import keyring
from keyring.backend import KeyringBackend
from keyring.errors import KeyringError

from documentation.server import CustomHTTPRequestHandler
from util import credentials


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


class FailingKeyring(InMemoryKeyring):
    def set_password(self, service, username, password):
        raise KeyringError("no backend")


LEGACY_CONFIG = {
    "default": ["DEMO", "Alice"],
    "logins": {
        "DEMO": {
            "url": "https://demo.example.com",
            "names": {
                "Alice": {"login": "alice", "password": "s3cret"},
                "Bob": {"login": "bob", "password": ""},
            },
        }
    },
}


class CredentialsTest(unittest.TestCase):
    def setUp(self):
        self.previous = keyring.get_keyring()
        self.backend = InMemoryKeyring()
        keyring.set_keyring(self.backend)

    def tearDown(self):
        keyring.set_keyring(self.previous)

    def test_migration_moves_passwords_out_of_config(self):
        data = copy.deepcopy(LEGACY_CONFIG)

        self.assertTrue(credentials.migrate_plaintext_passwords(data))

        names = data["logins"]["DEMO"]["names"]
        self.assertEqual(names, {"Alice": {"login": "alice"}, "Bob": {"login": "bob"}})
        self.assertEqual(credentials.get_password("https://demo.example.com", "alice"), "s3cret")
        self.assertEqual(credentials.get_password("https://demo.example.com", "bob"), "")

    def test_migration_is_idempotent(self):
        data = copy.deepcopy(LEGACY_CONFIG)
        credentials.migrate_plaintext_passwords(data)

        self.assertFalse(credentials.migrate_plaintext_passwords(data))

    def test_migration_keeps_every_password_when_store_unavailable(self):
        """Whichever of several real passwords Python happens to look at first, none of them is lost."""
        keyring.set_keyring(FailingKeyring())
        data = copy.deepcopy(LEGACY_CONFIG)
        data["logins"]["DEMO"]["names"]["Carl"] = {"login": "carl", "password": "t0psecret"}

        with self.assertRaises(KeyringError):
            credentials.migrate_plaintext_passwords(data)

        names = data["logins"]["DEMO"]["names"]
        self.assertEqual(names["Alice"]["password"], "s3cret")
        self.assertEqual(names["Carl"]["password"], "t0psecret")
        self.assertEqual(names["Bob"]["password"], "")
        self.assertIsNone(keyring.get_password(credentials.SERVICE_NAME, credentials.ACCOUNTS_ITEM))

    def test_migration_with_nothing_worth_storing_does_not_touch_the_store(self):
        """Only blank passwords: cleaned up in `data`, but there is nothing to fail storing, so it cannot raise."""
        keyring.set_keyring(FailingKeyring())
        data = {"logins": {"DEMO": {"url": "https://demo.example.com", "names": {
            "Bob": {"login": "bob", "password": ""}}}}}

        self.assertTrue(credentials.migrate_plaintext_passwords(data))

        self.assertEqual(data["logins"]["DEMO"]["names"]["Bob"], {"login": "bob"})

    def test_passwords_are_scoped_by_url(self):
        credentials.set_password("https://a.example.com", "alice", "one")
        credentials.set_password("https://b.example.com", "alice", "two")

        self.assertEqual(credentials.get_password("https://a.example.com", "alice"), "one")
        self.assertEqual(credentials.get_password("https://b.example.com", "alice"), "two")

    def test_every_account_shares_a_single_credential_store_item(self):
        """The whole point: macOS asks to allow access once for the application, not once per customer account."""
        credentials.set_password("https://a.example.com", "alice", "one")
        credentials.set_password("https://b.example.com", "bob", "two")
        credentials.migrate_plaintext_passwords(copy.deepcopy(LEGACY_CONFIG))

        self.assertEqual(list(self.backend.store), [(credentials.SERVICE_NAME, credentials.ACCOUNTS_ITEM)])

    def test_setting_one_password_does_not_disturb_another(self):
        credentials.set_password("https://a.example.com", "alice", "one")

        credentials.set_password("https://b.example.com", "bob", "two")

        self.assertEqual(credentials.get_password("https://a.example.com", "alice"), "one")

    def test_deleting_one_password_leaves_the_others(self):
        credentials.set_password("https://a.example.com", "alice", "one")
        credentials.set_password("https://b.example.com", "bob", "two")

        credentials.delete_password("https://a.example.com", "alice")

        self.assertEqual(credentials.get_password("https://a.example.com", "alice"), "")
        self.assertEqual(credentials.get_password("https://b.example.com", "bob"), "two")

    def test_deleting_a_password_that_was_never_stored_does_nothing(self):
        credentials.set_password("https://a.example.com", "alice", "one")

        credentials.delete_password("https://b.example.com", "nobody")

        self.assertEqual(credentials.get_password("https://a.example.com", "alice"), "one")

    def test_deleting_the_only_password_raises_nothing(self):
        credentials.delete_password("https://a.example.com", "alice")  # nothing stored yet, nothing to remove

    def test_a_password_asked_for_before_anything_was_ever_stored_is_empty(self):
        self.assertEqual(credentials.get_password("https://a.example.com", "alice"), "")

    def test_damaged_store_content_is_treated_as_nothing_stored(self):
        keyring.set_password(credentials.SERVICE_NAME, credentials.ACCOUNTS_ITEM, "{not json")

        self.assertEqual(credentials.get_password("https://a.example.com", "alice"), "")

    def test_store_content_that_is_not_an_object_is_treated_as_nothing_stored(self):
        keyring.set_password(credentials.SERVICE_NAME, credentials.ACCOUNTS_ITEM, "[1, 2, 3]")

        self.assertEqual(credentials.get_password("https://a.example.com", "alice"), "")

    def test_a_password_stored_over_damaged_content_does_not_destroy_the_content(self):
        keyring.set_password(credentials.SERVICE_NAME, credentials.ACCOUNTS_ITEM, "{not json")

        credentials.set_password("https://a.example.com", "alice", "pw")

        kept = [value for (service, item), value in self.backend.store.items()
                if item.startswith(credentials.ACCOUNTS_ITEM + ".unreadable-")]
        self.assertEqual(kept, ["{not json"])
        self.assertEqual(credentials.get_password("https://a.example.com", "alice"), "pw")

    def test_when_the_damaged_content_cannot_be_kept_nothing_is_written_over_it(self):
        class FailsNewItems(InMemoryKeyring):
            def set_password(self, service, username, password):
                if username != credentials.ACCOUNTS_ITEM:
                    raise KeyringError("cannot keep a copy")
                super().set_password(service, username, password)
        backend = FailsNewItems()
        keyring.set_keyring(backend)
        backend.store[(credentials.SERVICE_NAME, credentials.ACCOUNTS_ITEM)] = "[1, 2]"

        with self.assertRaises(KeyringError):
            credentials.set_password("https://a.example.com", "alice", "pw")
        with self.assertRaises(KeyringError):
            credentials.delete_password("https://a.example.com", "alice")

        self.assertEqual(backend.store[(credentials.SERVICE_NAME, credentials.ACCOUNTS_ITEM)], "[1, 2]")

    def test_readable_content_is_updated_without_any_copy_of_it(self):
        credentials.set_password("https://a.example.com", "alice", "pw")
        credentials.set_password("https://b.example.com", "bob", "pw2")

        self.assertEqual([item for _, item in self.backend.store], [credentials.ACCOUNTS_ITEM])
        self.assertEqual(credentials.get_password("https://a.example.com", "alice"), "pw")

    def test_get_password_reports_no_store_available_as_empty(self):
        class FailsReading(InMemoryKeyring):
            def get_password(self, service, username):
                raise KeyringError("no backend")
        keyring.set_keyring(FailsReading())

        self.assertEqual(credentials.get_password("https://a.example.com", "alice"), "")


def account_config(*accounts) -> dict:
    """A minimal config with one account per (url, login) pair, enough for migrate_per_account_items to read."""
    logins = {}
    for index, (url, login) in enumerate(accounts):
        logins[f"account{index}"] = {"url": url, "names": {login: {"login": login}}}
    return {"logins": logins}


class MigratePerAccountItemsTest(unittest.TestCase):
    """The shape every account's password used to be stored in, one item each, before they shared one."""

    def setUp(self):
        self.previous = keyring.get_keyring()
        self.backend = InMemoryKeyring()
        keyring.set_keyring(self.backend)
        self.addCleanup(keyring.set_keyring, self.previous)

    def store_old_item(self, url: str, login: str, password: str) -> None:
        keyring.set_password(credentials.SERVICE_NAME, credentials._key(url, login), password)

    def test_moves_an_old_item_into_the_shared_one_and_removes_it(self):
        self.store_old_item("https://demo.example.com", "alice", "s3cret")
        data = account_config(("https://demo.example.com", "alice"))

        self.assertTrue(credentials.migrate_per_account_items(data))

        self.assertEqual(credentials.get_password("https://demo.example.com", "alice"), "s3cret")
        self.assertIsNone(keyring.get_password(credentials.SERVICE_NAME,
                                               credentials._key("https://demo.example.com", "alice")))

    def test_several_old_items_are_all_moved(self):
        self.store_old_item("https://a.example.com", "alice", "one")
        self.store_old_item("https://b.example.com", "bob", "two")
        data = account_config(("https://a.example.com", "alice"), ("https://b.example.com", "bob"))

        self.assertTrue(credentials.migrate_per_account_items(data))

        self.assertEqual(credentials.get_password("https://a.example.com", "alice"), "one")
        self.assertEqual(credentials.get_password("https://b.example.com", "bob"), "two")

    def test_it_never_repeats_itself(self):
        self.store_old_item("https://demo.example.com", "alice", "s3cret")
        data = account_config(("https://demo.example.com", "alice"))
        credentials.migrate_per_account_items(data)

        self.assertFalse(credentials.migrate_per_account_items(data))

    def test_an_account_that_never_had_an_old_item_costs_nothing(self):
        data = account_config(("https://demo.example.com", "alice"))

        self.assertFalse(credentials.migrate_per_account_items(data))
        self.assertEqual(credentials.get_password("https://demo.example.com", "alice"), "")

    def test_an_old_item_is_kept_when_the_shared_store_cannot_be_written(self):
        self.store_old_item("https://demo.example.com", "alice", "s3cret")
        data = account_config(("https://demo.example.com", "alice"))
        failing = FailingKeyring()
        failing.store = self.backend.store  # the old item stays visible; only writing the shared one fails
        keyring.set_keyring(failing)

        with self.assertRaises(KeyringError):
            credentials.migrate_per_account_items(data)

        keyring.set_keyring(self.backend)
        self.assertEqual(credentials.get_password("https://demo.example.com", "alice"), "")
        self.assertEqual(keyring.get_password(credentials.SERVICE_NAME,
                                              credentials._key("https://demo.example.com", "alice")), "s3cret")


class MigrateCredentialItemsThroughTheAppTest(unittest.TestCase):
    """The whole path: the app moves an old, per-account item into the shared one as soon as it starts."""

    def setUp(self):
        self.previous_keyring = keyring.get_keyring()
        self.backend = InMemoryKeyring()
        keyring.set_keyring(self.backend)
        self.addCleanup(keyring.set_keyring, self.previous_keyring)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config_path = os.path.join(self.directory.name, "logins.json")
        config = {"lang": "cz", "font": ["Helvetica", 12], "default": ["", ""],
                 "logins": {"Demo": {"url": "https://demo.example.com", "names": {"alice": {"login": "alice"}}}}}
        with open(self.config_path, "w", encoding="utf-8") as file:
            json.dump(config, file)
        keyring.set_password(credentials.SERVICE_NAME, credentials._key("https://demo.example.com", "alice"),
                             "s3cret")

    def start_app(self):
        from gui_app import gui
        try:
            app = gui.DSMediaplayApp(self.config_path)
        except __import__("tkinter").TclError:
            self.skipTest("no display available")
        self.addCleanup(app.destroy)
        return app

    def test_the_old_item_ends_up_in_the_shared_one(self):
        self.start_app()

        self.assertEqual(credentials.get_password("https://demo.example.com", "alice"), "s3cret")
        self.assertIsNone(keyring.get_password(credentials.SERVICE_NAME,
                                               credentials._key("https://demo.example.com", "alice")))

    def test_the_account_itself_is_left_exactly_as_it_was(self):
        """Only the credential store changes; other startup migrations (e.g. legacy import) may still touch the
        file for their own reasons, but this one has nothing to save and adds no "password" field of its own."""
        self.start_app()

        with open(self.config_path, encoding="utf-8") as file:
            self.assertEqual(json.load(file)["logins"],
                             {"Demo": {"url": "https://demo.example.com", "names": {"alice": {"login": "alice"}}}})

    def test_a_store_failure_shows_a_warning_but_still_starts(self):
        failing = FailingKeyring()
        failing.store = self.backend.store
        keyring.set_keyring(failing)

        with patch("gui_app.gui.messagebox.showwarning") as warning:
            self.start_app()

        warning.assert_called_once()


class DocumentationServerTest(unittest.TestCase):
    def setUp(self):
        self.handler = CustomHTTPRequestHandler.__new__(CustomHTTPRequestHandler)

    def test_index_is_resolved_inside_pages(self):
        path = self.handler.resolve_path("/cz/")

        self.assertTrue(str(path).replace("\\", "/").endswith("documentation/pages/cz/index.html"))

    def test_a_missing_damaged_or_odd_config_is_the_defaults_and_accents_are_read(self):
        import tempfile
        from documentation.server import load_config
        with tempfile.TemporaryDirectory() as folder:
            def written(content, name="c.json"):
                path = os.path.join(folder, name)
                with open(path, "wb") as file:
                    file.write(content)
                return path

            self.assertEqual(load_config(os.path.join(folder, "none.json")), {})
            self.assertEqual(load_config(written(b"{ not json")), {})
            self.assertEqual(load_config(written(b"[1, 2]")), {})
            self.assertEqual(load_config(written(b"\xff\xfe\x00")), {})  # not text at all
            self.assertEqual(load_config(written('{"jméno": "Škoda"}'.encode("utf-8"))), {"jméno": "Škoda"})

    def test_parent_directory_segments_are_rejected(self):
        for request in ("/../../etc/passwd", "/en/../../../etc/passwd", "/assets/../../../etc/passwd"):
            with self.subTest(request=request):
                self.assertIsNone(self.handler.resolve_path(request))


if __name__ == "__main__":
    unittest.main()
