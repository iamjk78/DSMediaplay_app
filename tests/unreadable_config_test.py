"""A damaged account list used to stop the application from starting at all, with nothing to say about it."""
import glob
import json
import os
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from gui_app import gui

GOOD = {"lang": "cz", "font": ["Helvetica", 12], "default": ["Demo", "jane"],
        "logins": {"Demo": {"url": "https://demo.example.com", "names": {"jane": {"login": "jane"}}}}}


class UnreadableConfigTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            tk.Tk().destroy()
        except tk.TclError:
            raise unittest.SkipTest("no display available")

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = os.path.join(self.directory.name, "logins.json")
        for patcher in (patch("gui_app.gui.credentials.get_password", return_value=""),
                        patch.object(gui.DSMediaplayApp, "ask_language")):  # a fresh start asks for the language
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, text):
        with open(self.path, "w", encoding="utf-8") as file:
            file.write(text)

    def start(self):
        app = gui.DSMediaplayApp(self.path)
        self.addCleanup(self.close, app)
        app.update()
        return app

    @staticmethod
    def close(app):
        try:
            app.destroy()
        except tk.TclError:  # the test has destroyed it already
            pass

    def backups(self):
        return glob.glob(self.path + ".unreadable-*")

    def test_a_damaged_file_is_kept_next_to_it_and_the_application_starts_with_no_accounts(self):
        self.write("{ this is not json")

        with patch("gui_app.gui.messagebox.askyesno", return_value=True) as ask:
            app = self.start()

        self.assertEqual(app.account_data, {})
        (backup,) = self.backups()
        with open(backup, encoding="utf-8") as file:
            self.assertEqual(file.read(), "{ this is not json")  # nothing of it is lost
        title, text = ask.call_args.args
        for fragment in (self.path, backup, "Soubor s účty", "The account list"):  # in both languages
            self.assertIn(fragment, text)
        self.assertIn("/", title)
        self.assertEqual(ask.call_args.kwargs["default"], "yes")

    def test_a_file_that_is_json_but_not_an_object_is_treated_the_same_way(self):
        for content in ("[]", "42", '"text"', "null"):
            with self.subTest(content=content):
                self.write(content)
                with patch("gui_app.gui.messagebox.askyesno", return_value=True):
                    app = self.start()

                self.assertEqual(app.account_data, {})
                app.destroy()
                for backup in self.backups():
                    os.remove(backup)

    def test_the_application_that_starts_empty_saves_a_good_file_again(self):
        self.write("{ broken")
        with patch("gui_app.gui.messagebox.askyesno", return_value=True):
            app = self.start()

        app.all_data["logins"]["New"] = {"url": "https://new.example.com", "names": {}}
        app.save_account_configs()

        with open(self.path, encoding="utf-8") as file:
            self.assertIn("New", json.load(file)["logins"])

    def test_declining_quits_and_leaves_the_file_exactly_as_it_was(self):
        self.write("{ this is not json")

        with patch("gui_app.gui.messagebox.askyesno", return_value=False):
            with self.assertRaises(SystemExit):
                self.start()

        with open(self.path, encoding="utf-8") as file:
            self.assertEqual(file.read(), "{ this is not json")
        self.assertEqual(self.backups(), [])

    def test_when_the_copy_cannot_be_made_the_application_quits_and_says_why(self):
        self.write("{ this is not json")

        with patch("gui_app.gui.messagebox.askyesno", return_value=True), \
                patch("gui_app.gui.messagebox.showerror") as error, \
                patch("gui_app.gui.os.replace", side_effect=PermissionError("read-only")):
            with self.assertRaises(SystemExit):
                self.start()

        self.assertIn("read-only", error.call_args.args[1])
        with open(self.path, encoding="utf-8") as file:
            self.assertEqual(file.read(), "{ this is not json")

    def test_a_good_file_and_a_missing_file_ask_nothing(self):
        for content in (json.dumps(GOOD), None):
            with self.subTest(file="good" if content else "missing"):
                if content:
                    self.write(content)
                elif os.path.exists(self.path):
                    os.remove(self.path)
                with patch("gui_app.gui.messagebox.askyesno") as ask:
                    app = self.start()

                ask.assert_not_called()
                app.destroy()

    def test_a_file_that_gets_damaged_while_the_application_runs_does_not_break_it(self):
        self.write(json.dumps(GOOD))
        app = self.start()
        self.write("{ damaged meanwhile")

        app.reload_account_configs()  # what the refresh of the window after the settings does

        self.assertIn("Demo", app.account_data)


if __name__ == "__main__":
    unittest.main()
