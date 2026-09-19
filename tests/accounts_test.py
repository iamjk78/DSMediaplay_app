import unittest

from util.accounts import AccountError, add_account, add_login, normalize_url


def empty_config() -> dict:
    return {"default": ["", ""], "logins": {}}


class NormalizeUrlTest(unittest.TestCase):
    def test_accepts_https_and_strips_trailing_slash(self):
        self.assertEqual(normalize_url("  https://acme.signage.dsmediaplay.com/ "), "https://acme.signage.dsmediaplay.com")

    def test_accepts_underscore_hostname(self):
        self.assertEqual(normalize_url("https://shop_admin.signage.dsmediaplay.com"),
                         "https://shop_admin.signage.dsmediaplay.com")

    def test_rejects_addresses_that_would_leak_or_misdirect_credentials(self):
        for raw in ("http://acme.signage.dsmediaplay.com", "acme.signage.dsmediaplay.com", "https://",
                    "https://user:pw@evil.example", "https://host.example/?next=x", "https://host.example/#x",
                    "https://host .example", "ftp://host.example", ""):
            with self.subTest(raw=raw):
                with self.assertRaises(AccountError) as context:
                    normalize_url(raw)
                self.assertEqual(context.exception.key, "url_invalid")


class AddAccountTest(unittest.TestCase):
    def test_adds_account_with_empty_logins(self):
        data = empty_config()

        name = add_account(data, " Demo ", "https://demo.example.com/")

        self.assertEqual(name, "Demo")
        self.assertEqual(data["logins"], {"Demo": {"url": "https://demo.example.com", "names": {}}})

    def test_rejects_blank_and_duplicate_names_without_changing_config(self):
        data = empty_config()
        add_account(data, "Demo", "https://demo.example.com")
        before = repr(data)

        for name, key in (("  ", "account_name_required"), ("Demo", "account_exists")):
            with self.subTest(name=name):
                with self.assertRaises(AccountError) as context:
                    add_account(data, name, "https://other.example.com")
                self.assertEqual(context.exception.key, key)
        self.assertEqual(repr(data), before)

    def test_invalid_url_does_not_leave_a_half_added_account(self):
        data = empty_config()

        with self.assertRaises(AccountError):
            add_account(data, "Demo", "http://demo.example.com")

        self.assertEqual(data["logins"], {})


class AddLoginTest(unittest.TestCase):
    def setUp(self):
        self.data = empty_config()
        add_account(self.data, "Demo", "https://demo.example.com")

    def test_adds_login_without_any_password(self):
        login = add_login(self.data, "Demo", " jane.doe ")

        self.assertEqual(login, "jane.doe")
        self.assertEqual(self.data["logins"]["Demo"]["names"], {"jane.doe": {"login": "jane.doe"}})

    def test_rejects_blank_and_duplicate_logins(self):
        add_login(self.data, "Demo", "jane.doe")

        for login, key in ((" ", "login_required"), ("jane.doe", "login_exists")):
            with self.subTest(login=login):
                with self.assertRaises(AccountError) as context:
                    add_login(self.data, "Demo", login)
                self.assertEqual(context.exception.key, key)


if __name__ == "__main__":
    unittest.main()
