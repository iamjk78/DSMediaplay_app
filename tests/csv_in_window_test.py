"""Making a CSV file reads the server for seconds. It used to freeze the window (Windows: "Not responding") and every
failure, a wrong password included, was reported as "the data could not be saved"."""
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import requests

from api_testing.request_calls import LoginError, ResponseError
from gui_app import gui
from settings_and_log_window_test import WindowCase


class CsvInWindowTest(WindowCase):
    def make_csv(self, generate):
        """Runs the action with a task that does `generate(path)`, and returns the info and warning dialogs."""
        task = MagicMock()
        task.generate_csv.side_effect = generate
        with patch("gui_app.gui.CSVTaskFactory.create_task", return_value=task), \
                patch("gui_app.gui.get_download_path", return_value=self.directory.name), \
                patch("gui_app.gui.messagebox.showinfo") as info, patch("gui_app.gui.messagebox.showwarning") as warning:
            self.app.generate_csv("players", "https://x.example.com", "jane", "pw")
            self.wait_until(lambda: info.called or warning.called)
        return info, warning

    def wait_until(self, done, seconds=5):
        end = time.monotonic() + seconds
        while not done() and time.monotonic() < end:
            self.app.update()
            time.sleep(0.01)
        self.assertTrue(done(), "the action has not finished")

    def test_the_window_stays_alive_while_the_file_is_made(self):
        started, release = threading.Event(), threading.Event()

        def slow(path):
            started.set()
            release.wait(5)

        task = MagicMock()
        task.generate_csv.side_effect = slow
        with patch("gui_app.gui.CSVTaskFactory.create_task", return_value=task), \
                patch("gui_app.gui.get_download_path", return_value=self.directory.name), \
                patch("gui_app.gui.messagebox.showinfo") as info:
            self.app.generate_csv("players", "https://x.example.com", "jane", "pw")  # returns at once
            self.assertTrue(started.wait(2))
            self.app.update()
            self.assertEqual(self.app.cget("cursor"), "watch")
            info.assert_not_called()
            release.set()
            self.wait_until(lambda: info.called)

        self.assertEqual(self.app.cget("cursor"), "")

    def test_a_file_that_was_made_is_announced_with_its_path(self):
        info, warning = self.make_csv(lambda path: None)

        self.assertIn(self.directory.name, info.call_args.args[1])
        warning.assert_not_called()

    def test_each_kind_of_failure_says_what_it_is(self):
        cases = {
            "a wrong password": (LoginError(), self.app.lang.get_message("login_error")),
            "a disk that cannot be written": (PermissionError("read-only"), self.app.lang.get_message("file_save_error")),
            "a server that refuses": (ResponseError(params={}, status=500, request="GET /players"), "500"),
            "a network that is gone": (requests.exceptions.ConnectionError("no route"), "no route"),
        }
        for what, (error, expected) in cases.items():
            with self.subTest(what):
                def fail(path, error=error):
                    raise error
                info, warning = self.make_csv(fail)

                info.assert_not_called()
                self.assertIn(expected, warning.call_args.args[1])
                self.assertEqual(self.app.cget("cursor"), "")

    def test_a_second_click_while_the_first_file_is_made_does_not_start_another(self):
        release = threading.Event()
        task = MagicMock()
        task.generate_csv.side_effect = lambda path: release.wait(5)
        with patch("gui_app.gui.CSVTaskFactory.create_task", return_value=task), \
                patch("gui_app.gui.get_download_path", return_value=self.directory.name), \
                patch("gui_app.gui.messagebox.showinfo") as info:
            self.app.generate_csv("players", "https://x.example.com", "jane", "pw")
            self.app.generate_csv("players", "https://x.example.com", "jane", "pw")
            release.set()
            self.wait_until(lambda: info.called)

        self.assertEqual(task.generate_csv.call_count, 1)


class LoginCheckInWindowTest(WindowCase):
    """The button that saves the password asks the server whether the login works, which takes seconds too."""

    def setUp(self):
        super().setUp()
        self.app.all_data["logins"]["Demo"] = {"url": "https://x.example.com", "names": {"jane": {"login": "jane"}}}
        self.app.account_data = self.app.all_data["logins"]
        self.app.save_account_configs()
        self.app.option_choose_administration.set("Demo")
        self.app.fill_login_details()
        self.app.option_choose_name.set("jane")
        self.app.input_for_password.insert(0, "pw")

    def wait_until(self, done, seconds=5):
        end = time.monotonic() + seconds
        while not done() and time.monotonic() < end:
            self.app.update()
            time.sleep(0.01)
        self.assertTrue(done(), "the action has not finished")

    def save(self, check):
        with patch("gui_app.gui.try_login", side_effect=check), \
                patch("gui_app.gui.credentials.set_password") as store, \
                patch("gui_app.gui.messagebox.showinfo") as info, patch("gui_app.gui.messagebox.showerror") as error:
            self.app.save_login_details()
            self.wait_until(lambda: info.called or error.called or not self.app._login_check_running)
            self.app.update()
        return store, info, error

    def test_a_working_login_has_its_password_stored(self):
        store, info, error = self.save(lambda url, login, password: True)

        store.assert_called_once_with("https://x.example.com", "jane", "pw")
        info.assert_called_once()
        error.assert_not_called()
        self.assertEqual(self.app.cget("cursor"), "")

    def test_the_window_is_not_held_while_the_server_is_asked(self):
        asked, release = threading.Event(), threading.Event()

        def slow(url, login, password):
            asked.set()
            release.wait(5)
            return True

        with patch("gui_app.gui.try_login", side_effect=slow) as asking, patch("gui_app.gui.credentials.set_password"), \
                patch("gui_app.gui.messagebox.showinfo") as info:
            self.app.save_login_details()  # returns at once
            self.assertTrue(asked.wait(2))
            self.app.update()
            self.assertEqual(self.app.cget("cursor"), "watch")
            info.assert_not_called()
            self.app.save_login_details()  # a second click does not ask again
            release.set()
            self.wait_until(lambda: info.called)

        self.assertEqual(asking.call_count, 1)

    def test_a_wrong_password_and_an_unreachable_server_are_told_apart_and_store_nothing(self):
        for what, check, expected in (
                ("wrong password", lambda url, login, password: False, self.app.lang.get_message("save_failure")),
                ("no network", requests.exceptions.ConnectionError("no route"), "no route")):
            with self.subTest(what):
                store, info, error = self.save(check)

                store.assert_not_called()
                info.assert_not_called()
                self.assertIn(expected, " ".join(str(arg) for arg in error.call_args.args))

    def test_a_login_removed_while_the_server_was_asked_is_not_brought_back(self):
        asked, release = threading.Event(), threading.Event()

        def slow(url, login, password):
            asked.set()
            release.wait(5)
            return True

        with patch("gui_app.gui.try_login", side_effect=slow), \
                patch("gui_app.gui.credentials.set_password") as store, \
                patch("gui_app.gui.messagebox.showinfo") as info:
            self.app.save_login_details()
            self.assertTrue(asked.wait(2))
            del self.app.all_data["logins"]["Demo"]["names"]["jane"]
            self.app.save_account_configs()
            release.set()
            self.wait_until(lambda: not self.app._login_check_running)

        store.assert_not_called()
        info.assert_not_called()
        self.assertNotIn("jane", self.saved()["logins"]["Demo"]["names"])


if __name__ == "__main__":
    unittest.main()
