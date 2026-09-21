import unittest

from util.accounts import (AccountError, add_account, add_login, hidden_player_columns, normalize_url, player_columns,
                           player_font_size, remember_selection, remove_account, remove_login,
                           set_hidden_player_columns, set_player_columns, set_player_font_size,
                           set_snapshot_window_size, snapshot_window_size)


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


def config_with_two_accounts() -> dict:
    data = empty_config()
    add_account(data, "A", "https://a.example.com")
    add_account(data, "B", "https://b.example.com")
    for account, logins in (("A", ("a1", "a2")), ("B", ("b1",))):
        for login in logins:
            add_login(data, account, login)
    return data


class RememberSelectionTest(unittest.TestCase):
    def test_remembers_last_account_and_its_last_login(self):
        data = config_with_two_accounts()

        self.assertTrue(remember_selection(data, "A", "a2"))
        self.assertTrue(remember_selection(data, "B", "b1"))

        self.assertEqual(data["default"], ["B", "b1"])
        self.assertEqual(data["logins"]["A"]["last"], "a2")
        self.assertEqual(data["logins"]["B"]["last"], "b1")

    def test_selecting_an_account_without_login_keeps_its_previous_last_login(self):
        data = config_with_two_accounts()
        remember_selection(data, "A", "a1")
        remember_selection(data, "B", "b1")

        remember_selection(data, "A", "")

        self.assertEqual(data["default"], ["A", "a1"])

    def test_reports_no_change_when_nothing_differs(self):
        data = config_with_two_accounts()
        remember_selection(data, "A", "a1")

        self.assertFalse(remember_selection(data, "A", "a1"))

    def test_ignores_a_login_that_does_not_belong_to_the_account(self):
        data = config_with_two_accounts()

        remember_selection(data, "A", "b1")

        self.assertNotIn("last", data["logins"]["A"])
        self.assertEqual(data["default"], ["A", ""])


class RemoveTest(unittest.TestCase):
    def test_remove_login_returns_its_credential_and_clears_the_pointers(self):
        data = config_with_two_accounts()
        remember_selection(data, "A", "a1")

        unused = remove_login(data, "A", "a1")

        self.assertEqual(unused, [("https://a.example.com", "a1")])
        self.assertNotIn("a1", data["logins"]["A"]["names"])
        self.assertNotIn("last", data["logins"]["A"])
        self.assertEqual(data["default"], ["A", ""])

    def test_remove_login_keeps_the_password_another_entry_still_uses(self):
        data = config_with_two_accounts()
        data["logins"]["A"]["names"]["a1 copy"] = {"login": "a1"}  # same URL and login, another display name

        self.assertEqual(remove_login(data, "A", "a1"), [])
        self.assertEqual(remove_login(data, "A", "a1 copy"), [("https://a.example.com", "a1")])

    def test_remove_account_returns_all_its_credentials_and_resets_default(self):
        data = config_with_two_accounts()
        remember_selection(data, "A", "a2")

        unused = remove_account(data, "A")

        self.assertEqual(unused, [("https://a.example.com", "a1"), ("https://a.example.com", "a2")])
        self.assertNotIn("A", data["logins"])
        self.assertEqual(data["default"], ["", ""])

    def test_remove_account_keeps_credentials_used_by_another_account_with_the_same_url(self):
        data = config_with_two_accounts()
        add_account(data, "A again", "https://a.example.com")
        add_login(data, "A again", "a1")

        self.assertEqual(remove_account(data, "A"), [("https://a.example.com", "a2")])

    def test_removing_another_account_leaves_default_alone(self):
        data = config_with_two_accounts()
        remember_selection(data, "A", "a1")

        remove_account(data, "B")

        self.assertEqual(data["default"], ["A", "a1"])


class PlayerColumnsTest(unittest.TestCase):
    def config(self):
        data = empty_config()
        add_account(data, "A", "https://a.example.com")
        add_account(data, "B", "https://b.example.com")
        return data

    def test_the_widths_are_kept_per_account(self):
        data = self.config()

        set_player_columns(data, "A", {"name": 300, "group": 150})

        self.assertEqual(player_columns(data, "A"), {"name": 300, "group": 150})
        self.assertEqual(player_columns(data, "B"), {})

    def test_an_empty_dict_forgets_the_widths(self):
        data = self.config()
        set_player_columns(data, "A", {"name": 300})

        set_player_columns(data, "A", {})

        self.assertNotIn("player_columns", data["logins"]["A"])

    def test_an_unknown_account_has_no_widths(self):
        self.assertEqual(player_columns(self.config(), "nope"), {})

    def test_the_widths_go_away_with_the_account_and_do_not_disturb_the_rest(self):
        data = self.config()
        add_login(data, "A", "jane")
        set_player_columns(data, "A", {"name": 300})

        self.assertEqual(remove_login(data, "A", "jane"), [("https://a.example.com", "jane")])
        self.assertEqual(player_columns(data, "A"), {"name": 300})
        remove_account(data, "A")
        self.assertEqual(player_columns(data, "A"), {})

    def test_the_returned_dict_is_a_copy(self):
        data = self.config()
        set_player_columns(data, "A", {"name": 300})

        player_columns(data, "A")["name"] = 1

        self.assertEqual(player_columns(data, "A"), {"name": 300})


class HiddenPlayerColumnsTest(unittest.TestCase):
    DEFAULT = ["temperature", "version"]

    def config(self):
        data = empty_config()
        add_account(data, "A", "https://a.example.com")
        add_account(data, "B", "https://b.example.com")
        return data

    def test_an_account_that_never_chose_has_the_default_columns_off(self):
        data = self.config()

        self.assertEqual(hidden_player_columns(data, "A"), self.DEFAULT)
        self.assertEqual(hidden_player_columns(data, "nope"), self.DEFAULT)

    def test_kept_per_account_and_the_defaults_again_store_nothing(self):
        data = self.config()

        set_hidden_player_columns(data, "A", ["group", "note", "temperature", "version"])

        self.assertEqual(hidden_player_columns(data, "A"), ["group", "note", "temperature", "version"])
        self.assertEqual(hidden_player_columns(data, "B"), self.DEFAULT)
        set_hidden_player_columns(data, "A", self.DEFAULT)
        self.assertNotIn("player_hidden", data["logins"]["A"])
        self.assertNotIn("player_shown", data["logins"]["A"])
        self.assertEqual(hidden_player_columns(data, "A"), self.DEFAULT)

    def test_only_the_difference_from_the_defaults_is_stored(self):
        data = self.config()

        set_hidden_player_columns(data, "A", ["synced", "version"])  # the temperature is on, the synced is off

        self.assertEqual(data["logins"]["A"]["player_hidden"], ["synced"])
        self.assertEqual(data["logins"]["A"]["player_shown"], ["temperature"])
        self.assertEqual(hidden_player_columns(data, "A"), ["synced", "version"])

    def test_everything_shown_is_kept_too(self):
        data = self.config()

        set_hidden_player_columns(data, "A", [])

        self.assertEqual(hidden_player_columns(data, "A"), [])
        self.assertEqual(data["logins"]["A"]["player_shown"], ["temperature", "version"])

    def test_an_account_saved_before_the_new_columns_existed_has_them_off(self):
        data = self.config()
        data["logins"]["A"]["player_hidden"] = ["synced", "note"]

        self.assertEqual(hidden_player_columns(data, "A"), ["note", "synced", "temperature", "version"])

    def test_independent_of_the_widths_and_a_copy(self):
        data = self.config()
        set_player_columns(data, "A", {"name": 300})
        set_hidden_player_columns(data, "A", ["note", "temperature", "version"])

        hidden_player_columns(data, "A").append("group")
        set_player_columns(data, "A", {})

        self.assertEqual(hidden_player_columns(data, "A"), ["note", "temperature", "version"])


class PlayerFontSizeTest(unittest.TestCase):
    def config(self):
        data = empty_config()
        add_account(data, "A", "https://a.example.com")
        add_account(data, "B", "https://b.example.com")
        return data

    def test_kept_per_account_and_none_forgets_it(self):
        data = self.config()

        set_player_font_size(data, "A", 15)

        self.assertEqual(player_font_size(data, "A"), 15)
        self.assertIsNone(player_font_size(data, "B"))
        self.assertIsNone(player_font_size(data, "nope"))
        set_player_font_size(data, "A", None)
        self.assertNotIn("player_font", data["logins"]["A"])

    def test_independent_of_the_widths_and_the_hidden_columns(self):
        data = self.config()
        set_player_columns(data, "A", {"name": 300})
        set_hidden_player_columns(data, "A", ["note"])

        set_player_font_size(data, "A", 9)
        set_player_columns(data, "A", {})

        self.assertEqual((player_font_size(data, "A"), hidden_player_columns(data, "A")), (9, ["note"]))

    def test_it_goes_away_with_the_account(self):
        data = self.config()
        set_player_font_size(data, "A", 12)

        remove_account(data, "A")

        self.assertIsNone(player_font_size(data, "A"))


class SnapshotWindowSizeTest(unittest.TestCase):
    def config(self):
        data = empty_config()
        add_account(data, "A", "https://a.example.com")
        add_account(data, "B", "https://b.example.com")
        return data

    def test_kept_per_account_and_none_forgets_it(self):
        data = self.config()

        set_snapshot_window_size(data, "A", (1100, 700))

        self.assertEqual(snapshot_window_size(data, "A"), [1100, 700])
        self.assertIsNone(snapshot_window_size(data, "B"))
        self.assertIsNone(snapshot_window_size(data, "nope"))
        set_snapshot_window_size(data, "A", None)
        self.assertNotIn("snapshot_window", data["logins"]["A"])

    def test_independent_of_the_other_settings_of_the_player_table(self):
        data = self.config()
        set_player_font_size(data, "A", 15)

        set_snapshot_window_size(data, "A", (1100, 700))
        set_snapshot_window_size(data, "A", None)

        self.assertEqual(player_font_size(data, "A"), 15)


if __name__ == "__main__":
    unittest.main()
