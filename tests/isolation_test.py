"""The tests must never reach the real passwords of the person who runs them."""
import os
import unittest

import keyring

from util import credentials


class IsolationTest(unittest.TestCase):
    def test_the_credential_store_of_a_test_is_a_private_one(self):
        self.assertEqual(type(keyring.get_keyring()).__name__, "InMemoryKeyring")
        credentials.set_password("https://isolation.example.com", "nobody", "secret")

        self.assertEqual(credentials.get_password("https://isolation.example.com", "nobody"), "secret")

    def test_the_old_apps_accounts_are_not_looked_for_in_the_real_profile(self):
        self.assertNotEqual(os.environ.get("APPDATA"), os.path.expanduser("~"))
        self.assertIn("appdata", os.environ["APPDATA"])


if __name__ == "__main__":
    unittest.main()
