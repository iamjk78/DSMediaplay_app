import copy
import unittest

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

    def test_migration_keeps_password_when_store_unavailable(self):
        keyring.set_keyring(FailingKeyring())
        data = copy.deepcopy(LEGACY_CONFIG)

        with self.assertRaises(KeyringError):
            credentials.migrate_plaintext_passwords(data)

        self.assertEqual(data["logins"]["DEMO"]["names"]["Alice"]["password"], "s3cret")

    def test_passwords_are_scoped_by_url(self):
        credentials.set_password("https://a.example.com", "alice", "one")
        credentials.set_password("https://b.example.com", "alice", "two")

        self.assertEqual(credentials.get_password("https://a.example.com", "alice"), "one")
        self.assertEqual(credentials.get_password("https://b.example.com", "alice"), "two")


class DocumentationServerTest(unittest.TestCase):
    def setUp(self):
        self.handler = CustomHTTPRequestHandler.__new__(CustomHTTPRequestHandler)

    def test_index_is_resolved_inside_pages(self):
        path = self.handler.resolve_path("/cz/")

        self.assertTrue(path.endswith("documentation/pages/cz/index.html"))

    def test_parent_directory_segments_are_rejected(self):
        for request in ("/../../etc/passwd", "/en/../../../etc/passwd", "/assets/../../../etc/passwd"):
            with self.subTest(request=request):
                self.assertIsNone(self.handler.resolve_path(request))


if __name__ == "__main__":
    unittest.main()
