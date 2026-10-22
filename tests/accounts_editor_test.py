"""The editor of accounts behind "Edit JSON" works through the functions the main window uses: addresses are checked,
the file is written whole, a change made outside is read first, and the passwords follow their logins."""
import json
import tkinter as tk
from unittest.mock import MagicMock, patch

from gui_app import gui
from json_manager.json_manager import JsonEditorApp
from settings_and_log_window_test import WindowCase, close
from util import credentials

URL = "https://demo.example.com"
OTHER_URL = "https://other.example.com"


class AccountsEditorTest(WindowCase):
    def start_app(self):
        """The window of the other tests has the stored passwords patched away; here the (in memory) store is used."""
        try:
            self.app = gui.DSMediaplayApp(self.config)
        except tk.TclError:
            self.skipTest("no display available")
        self.addCleanup(close, self.app)
        self.app.update()

    def setUp(self):
        super().setUp()
        self.app.all_data["logins"]["Demo"] = {"url": URL, "names": {"jane": {"login": "jane"},
                                                                      "john": {"login": "john"}}}
        self.app.account_data = self.app.all_data["logins"]
        self.app.save_account_configs()
        credentials.set_password(URL, "jane", "pw-jane")
        credentials.set_password(URL, "john", "pw-john")
        patcher = patch("json_manager.json_manager.messagebox")
        self.boxes = patcher.start()
        self.addCleanup(patcher.stop)
        self.boxes.askyesno.return_value = True
        self.editor = JsonEditorApp(self.app)
        self.addCleanup(self.editor.destroy)

    def pick(self, combobox, value):
        combobox.set(value)
        combobox.event_generate("<<ComboboxSelected>>")
        self.app.update()

    def file_logins(self):
        return self.saved()["logins"]

    def test_the_password_is_not_shown_while_it_is_typed(self):
        self.assertEqual(self.editor.password_entry.cget("show"), "*")

    def test_an_administration_is_added_with_a_checked_address(self):
        self.editor.admin_name_var.set("New")
        self.editor.admin_url_var.set(OTHER_URL + "/")

        self.editor.add_administration()

        self.assertEqual(self.file_logins()["New"], {"url": OTHER_URL, "names": {}})
        self.assertIn("New", self.app.account_data)
        self.assertIn("New", self.editor.admin_combobox.cget("values"))

    def test_an_address_that_would_send_the_password_in_the_clear_or_elsewhere_is_refused(self):
        for url in ("http://plain.example.com", "https://user:pw@evil.example.com", "https://x.example.com/?a=b",
                    "not a url", ""):
            with self.subTest(url=url):
                self.editor.admin_name_var.set("Bad")
                self.editor.admin_url_var.set(url)

                self.editor.add_administration()

                self.boxes.showwarning.assert_called()
                self.assertNotIn("Bad", self.file_logins())
                self.boxes.showwarning.reset_mock()

    def test_an_administration_with_the_name_of_another_is_refused(self):
        self.editor.admin_name_var.set("Demo")
        self.editor.admin_url_var.set(OTHER_URL)

        self.editor.add_administration()

        self.boxes.showwarning.assert_called()
        self.assertEqual(self.file_logins()["Demo"]["url"], URL)

    def test_deleting_an_administration_asks_and_takes_its_passwords_with_it(self):
        self.editor.delete_admin_combobox.set("Demo")
        self.boxes.askyesno.return_value = False
        self.editor.delete_administration()
        self.assertIn("Demo", self.file_logins())

        self.boxes.askyesno.return_value = True
        window = MagicMock()
        window.winfo_exists.return_value = True
        window.connection = (URL, "jane")
        self.app._player_browser = window
        self.editor.delete_admin_combobox.set("Demo")
        self.editor.delete_administration()

        self.assertNotIn("Demo", self.file_logins())
        self.assertEqual(credentials.get_password(URL, "jane"), "")
        window.destroy.assert_called_once()

    def test_a_new_address_takes_the_passwords_along_and_leaves_none_behind(self):
        self.editor.edit_admin_combobox.set("Demo")
        self.editor.new_url_var.set(OTHER_URL)

        self.editor.edit_url()

        self.assertEqual(self.file_logins()["Demo"]["url"], OTHER_URL)
        self.assertEqual(credentials.get_password(OTHER_URL, "jane"), "pw-jane")
        self.assertEqual(credentials.get_password(OTHER_URL, "john"), "pw-john")
        self.assertEqual(credentials.get_password(URL, "jane"), "")

    def test_a_wrong_new_address_or_a_failing_store_changes_nothing(self):
        self.editor.edit_admin_combobox.set("Demo")
        self.editor.new_url_var.set("http://plain.example.com")
        self.editor.edit_url()
        self.assertEqual(self.file_logins()["Demo"]["url"], URL)

        self.editor.new_url_var.set(OTHER_URL)
        with patch("json_manager.json_manager.credentials.set_password", side_effect=credentials.KeyringError("no")):
            self.editor.edit_url()

        self.assertEqual(self.file_logins()["Demo"]["url"], URL)
        self.assertEqual(credentials.get_password(URL, "jane"), "pw-jane")
        self.boxes.showerror.assert_called()

    def test_a_login_is_added_with_its_password_in_the_store_not_in_the_file(self):
        self.editor.admin_combobox.set("Demo")
        self.editor.display_name_var.set("")
        self.editor.login_name_var.set("anna")
        self.editor.password_var.set("secret-anna")

        self.editor.add_login()

        self.assertEqual(self.file_logins()["Demo"]["names"]["anna"], {"login": "anna"})
        self.assertEqual(credentials.get_password(URL, "anna"), "secret-anna")
        with open(self.config, encoding="utf-8") as file:
            self.assertNotIn("secret-anna", file.read())

    def test_adding_a_login_that_exists_and_editing_one_that_does_not_are_refused(self):
        self.editor.admin_combobox.set("Demo")
        self.editor.login_name_var.set("jane")
        self.editor.display_name_var.set("jane")
        self.editor.add_login()
        self.boxes.showwarning.assert_called()
        self.boxes.showwarning.reset_mock()

        self.editor.display_name_var.set("nobody")
        self.editor.login_name_var.set("nobody")
        self.editor.edit_login()

        self.boxes.showwarning.assert_called()
        self.assertNotIn("nobody", self.file_logins()["Demo"]["names"])

    def test_changing_the_login_of_an_entry_drops_the_password_of_the_old_one(self):
        self.editor.admin_combobox.set("Demo")
        self.editor.display_name_var.set("jane")
        self.editor.login_name_var.set("jane.new")
        self.editor.password_var.set("pw-new")

        self.editor.edit_login()

        self.assertEqual(self.file_logins()["Demo"]["names"]["jane"], {"login": "jane.new"})
        self.assertEqual(credentials.get_password(URL, "jane.new"), "pw-new")
        self.assertEqual(credentials.get_password(URL, "jane"), "")
        self.assertEqual(credentials.get_password(URL, "john"), "pw-john")

    def test_removing_a_login_takes_its_password_and_closes_its_player_window(self):
        window = MagicMock()
        window.winfo_exists.return_value = True
        window.connection = (URL, "jane")
        self.app._player_browser = window
        self.editor.admin_combobox.set("Demo")
        self.editor.login_combobox.set("jane")

        self.editor.remove_login()

        self.assertNotIn("jane", self.file_logins()["Demo"]["names"])
        self.assertEqual(credentials.get_password(URL, "jane"), "")
        self.assertEqual(credentials.get_password(URL, "john"), "pw-john")
        window.destroy.assert_called_once()

    def test_the_default_login_is_remembered_the_way_the_window_does_it(self):
        self.editor.default_admin_combobox.set("Demo")
        self.editor.update_default_login_combobox()
        self.editor.default_admin_combobox.set("Demo")
        self.editor.default_login_combobox.set("john")

        self.editor.set_default()

        self.assertEqual(self.saved()["default"], ["Demo", "john"])
        self.assertEqual(self.file_logins()["Demo"]["last"], "john")

    def test_a_change_made_outside_is_read_before_the_editor_writes(self):
        data = self.saved()
        data["logins"]["Outside"] = {"url": OTHER_URL, "names": {}}
        with open(self.config, "w", encoding="utf-8") as file:
            json.dump(data, file)
        self.editor.admin_name_var.set("Inside")
        self.editor.admin_url_var.set("https://inside.example.com")

        self.editor.add_administration()

        self.assertTrue({"Demo", "Outside", "Inside"} <= set(self.file_logins()))

    def test_the_selected_login_shows_its_stored_password(self):
        self.pick(self.editor.admin_combobox, "Demo")
        self.pick(self.editor.login_combobox, "jane")

        self.assertEqual(self.editor.password_var.get(), "pw-jane")
        self.assertEqual(self.editor.login_name_var.get(), "jane")
