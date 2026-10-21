"""The Save button of the log window and the font of the settings: both used to claim they worked and did not."""
import json
import os
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from gui_app import gui
from gui_app.log_box import LoggingTextBox
from gui_app.settings_dialog import SettingsWindow


def close(widget):
    try:
        if widget.winfo_exists():
            widget.destroy()
    except tk.TclError:  # the whole application is gone already
        pass


class WindowCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = os.path.join(self.directory.name, "logins.json")
        with open(self.config, "w", encoding="utf-8") as file:
            json.dump({"lang": "cz", "font": ["Helvetica", 12], "default": ["", ""], "logins": {}}, file)
        self.start_app()

    def start_app(self):
        patcher = patch("gui_app.gui.credentials.get_password", return_value="")
        patcher.start()
        self.addCleanup(patcher.stop)
        try:
            self.app = gui.DSMediaplayApp(self.config)
        except tk.TclError:
            self.skipTest("no display available")
        self.addCleanup(close, self.app)
        self.app.update()

    def saved(self):
        with open(self.config, encoding="utf-8") as file:
            return json.load(file)


class SaveLogTest(WindowCase):
    def open_box(self, text):
        with patch("gui_app.log_box.ThreadManager.start_thread"):
            box = LoggingTextBox("remove_unused_playlists", url="http://example.com", login="u", password="p",
                                 data="", master=self.app)
        self.addCleanup(close, box)
        box.log_text.configure(state="normal")
        box.log_text.insert("1.0", text)
        return box

    def test_the_log_is_saved_in_the_chosen_file_and_the_message_says_where(self):
        box = self.open_box("Řádek 1: úspěch")
        target = os.path.join(self.directory.name, "log.txt")

        with patch("gui_app.log_box.filedialog.asksaveasfilename", return_value=target), \
                patch("gui_app.log_box.messagebox.showinfo") as info:
            box.save_text()

        with open(target, encoding="utf-8") as file:
            self.assertEqual(file.read(), "Řádek 1: úspěch")
        self.assertIn(target, info.call_args.args[1])

    def test_cancelling_the_dialog_does_nothing_instead_of_failing(self):
        box = self.open_box("text")
        for answer in ("", ()):  # what the dialog gives back on the platforms
            with self.subTest(answer=answer):
                with patch("gui_app.log_box.filedialog.asksaveasfilename", return_value=answer), \
                        patch("gui_app.log_box.messagebox.showinfo") as info, \
                        patch("gui_app.log_box.messagebox.showwarning") as warning:
                    box.save_text()

                info.assert_not_called()
                warning.assert_not_called()

    def test_a_file_that_cannot_be_written_is_reported_to_the_user(self):
        box = self.open_box("text")

        with patch("gui_app.log_box.filedialog.asksaveasfilename", return_value=self.directory.name), \
                patch("gui_app.log_box.messagebox.showinfo") as info, \
                patch("gui_app.log_box.messagebox.showwarning") as warning:
            box.save_text()  # a folder, not a file

        warning.assert_called_once()
        info.assert_not_called()


class SettingsFontTest(WindowCase):
    def save_settings(self, font, size):
        window = SettingsWindow(self.app, self.app.lang)
        self.addCleanup(close, window)
        window.font_var.set(font)
        window.size_var.set(size)
        with patch("gui_app.settings_dialog.messagebox.showinfo"):
            window.save_settings()

    def test_the_chosen_font_is_saved_in_the_config_file(self):
        self.save_settings("Arial", 16)

        self.assertEqual(self.saved()["font"], ["Arial", 16])
        self.assertEqual(self.app.font, ("Arial", 16))

    def test_the_font_is_the_same_after_the_application_is_started_again(self):
        self.save_settings("Arial", 16)
        self.app.destroy()

        self.start_app()

        self.assertEqual(self.app.font, ("Arial", 16))
        self.assertEqual(self.app.emphasised_font(2), ("Arial", 18, "bold"))  # the size is a number, not a text

    def test_restoring_the_defaults_restores_the_font_in_the_file_too(self):
        self.save_settings("Arial", 16)
        window = SettingsWindow(self.app, self.app.lang)
        self.addCleanup(close, window)

        with patch("gui_app.settings_dialog.messagebox.showinfo"):
            window.restore_default()

        self.assertEqual(self.saved()["font"], ["Helvetica", 12])


if __name__ == "__main__":
    unittest.main()
