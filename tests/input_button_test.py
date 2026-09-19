import json
import os
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

import time

from gui_app import gui
from gui_app.color_button import GREEN, GREEN_DARK, ColorButton
from gui_app.gui import DSMediaplayApp
from util.actions import action_needs_input

DEFAULT_BLINK_INTERVAL_MS = gui.BLINK_INTERVAL_MS


class ActionNeedsInputTest(unittest.TestCase):
    def test_reading_actions_need_no_input(self):
        for action in ("get_playlist_details", "get_player_overview", "get_group_unused"):
            with self.subTest(action=action):
                self.assertFalse(action_needs_input(action))

    def test_removing_everything_and_deploying_to_all_players_need_no_input(self):
        for action in ("remove_all_unused_playlists", "remove_all_expired_playlists", "set_deploy_all_players"):
            with self.subTest(action=action):
                self.assertFalse(action_needs_input(action))

    def test_changing_creating_and_selective_removal_need_input(self):
        for action in ("set_group_rename", "create_playlist", "remove_unused_playlists", "remove_expired_playlists",
                       "remove_playlists_from_group", "set_deploy_selected_groups"):
            with self.subTest(action=action):
                self.assertTrue(action_needs_input(action))


class InputButtonTest(unittest.TestCase):
    def setUp(self):
        interval = patch.object(gui, "BLINK_INTERVAL_MS", 30)
        interval.start()
        self.addCleanup(interval.stop)
        self.directory = tempfile.TemporaryDirectory()
        path = os.path.join(self.directory.name, "logins.json")
        with open(path, "w", encoding="utf-8") as file:
            json.dump({"lang": "cz", "font": ["Helvetica", 12], "default": ["", ""], "logins": {}}, file)
        try:
            self.app = DSMediaplayApp(path)
        except tk.TclError:
            self.skipTest("no display available")
        self.app.update()

    def tearDown(self):
        if hasattr(self, "app"):
            self.app.destroy()
        self.directory.cleanup()

    def visible(self):
        self.app.update()
        return self.app.input_prompt_button.winfo_manager() == "grid"

    def choose(self, entity_type, action_key):
        self.app.entity_type_var.set(entity_type)
        self.app.update_action_selection()
        label = next(label for label, key in self.app.entity_actions[entity_type].items() if key == action_key)
        self.app.option_choose_action.set(label)
        self.app.reset_data()
        self.app.update()

    def test_hidden_until_an_action_is_chosen(self):
        self.assertFalse(self.visible())

    def test_shown_only_for_actions_that_need_input(self):
        self.choose("Playlists", "get_playlist_details")
        self.assertFalse(self.visible())

        self.choose("Playlists", "set_playlist_settings")
        self.assertTrue(self.visible())

        self.choose("Playlists", "remove_all_unused_playlists")
        self.assertFalse(self.visible())

        self.choose("Playlists", "create_playlist")
        self.assertTrue(self.visible())

    def test_deploy_all_players_is_selected_by_default_and_needs_no_input(self):
        self.app.entity_type_var.set("Deploy")
        self.app.update_action_selection()

        self.assertFalse(self.visible())

        self.choose("Deploy", "set_deploy_selected_groups")
        self.assertTrue(self.visible())

    def test_hidden_again_after_the_selection_is_cleared(self):
        self.choose("Playlists", "set_playlist_settings")

        self.app.refresh_ui()

        self.assertFalse(self.visible())

    def test_the_window_does_not_jump_when_the_button_comes_and_goes(self):
        self.choose("Playlists", "get_playlist_details")
        height = self.app.winfo_height()

        self.choose("Playlists", "set_playlist_settings")
        self.assertEqual(self.app.winfo_height(), height)

        self.app.update_font(("Helvetica", 18))
        self.app.refresh_ui()
        self.choose("Playlists", "get_playlist_details")
        height = self.app.winfo_height()
        self.choose("Playlists", "set_playlist_settings")
        self.assertEqual(self.app.winfo_height(), height)

    def test_input_typed_for_one_action_is_dropped_when_another_is_chosen(self):
        self.choose("Playlists", "set_playlist_settings")
        self.app._text_box_data = "typed"

        self.choose("Playlists", "get_playlist_details")

        self.assertIsNone(self.app._text_box_data)

    def fill(self):
        button = self.app.input_prompt_button
        if isinstance(button, ColorButton):
            return button.itemcget(button.find_withtag("all")[0], "fill")
        return button.cget("background")

    def fills_over(self, milliseconds):
        seen, end = [], time.monotonic() + milliseconds / 1000
        while time.monotonic() < end:
            self.app.update()
            seen.append(self.fill())
            time.sleep(0.004)
        return seen

    def test_the_blink_interval_is_half_a_second(self):
        self.assertEqual(DEFAULT_BLINK_INTERVAL_MS, 500)

    def test_blinks_between_light_and_dark_green_while_shown(self):
        self.choose("Playlists", "set_playlist_settings")

        seen = self.fills_over(400)

        self.assertEqual(set(seen), {GREEN.normal, GREEN_DARK.normal})

    def test_does_not_blink_when_the_button_is_hidden(self):
        self.choose("Playlists", "get_playlist_details")

        self.assertIsNone(self.app._blink_id)
        self.assertEqual(set(self.fills_over(200)), {GREEN.normal})

    def test_stops_and_returns_to_light_green_when_the_action_needs_no_input(self):
        self.choose("Playlists", "set_playlist_settings")
        self.fills_over(150)

        self.choose("Playlists", "get_playlist_details")

        self.assertIsNone(self.app._blink_id)
        self.assertEqual(set(self.fills_over(150)), {GREEN.normal})

    def test_choosing_actions_repeatedly_never_starts_a_second_blink_timer(self):
        self.choose("Playlists", "set_playlist_settings")
        timers = len(self.app.tk.call("after", "info"))

        for _ in range(5):
            self.app.update_input_button()
        self.choose("Groups", "set_group_rename")

        self.assertEqual(len(self.app.tk.call("after", "info")), timers)

    def test_the_text_is_always_bold(self):
        button = self.app.input_prompt_button
        self.assertEqual(button.cget("font"), ("Helvetica", 12, "bold"))

        self.choose("Playlists", "set_playlist_settings")
        self.fills_over(100)
        self.assertEqual(button.cget("font"), ("Helvetica", 12, "bold"))

        self.app.update_font(("Arial", 16))
        self.app.refresh_ui()
        self.assertEqual(button.cget("font"), ("Arial", 16, "bold"))

    def text_colour(self):
        button = self.app.input_prompt_button
        if isinstance(button, ColorButton):
            return button.itemcget(button.find_withtag("all")[1], "fill")
        return button.cget("foreground")

    def looks_over(self, milliseconds):
        seen, end = [], time.monotonic() + milliseconds / 1000
        while time.monotonic() < end:
            self.app.update()
            seen.append((self.fill(), self.text_colour()))
            time.sleep(0.004)
        return set(seen)

    def test_black_text_on_light_green_and_white_text_on_dark_green(self):
        self.choose("Playlists", "set_playlist_settings")

        self.assertEqual(self.looks_over(400), {(GREEN.normal, "#000000"), (GREEN_DARK.normal, "#ffffff")})

    def test_stops_blinking_once_the_user_has_entered_input(self):
        self.choose("Playlists", "set_playlist_settings")
        self.assertIsNotNone(self.app._blink_id)

        self.app.save_data_from_text_box("Playlist 1\n")

        self.assertIsNone(self.app._blink_id)
        self.assertEqual(self.looks_over(150), {(GREEN.normal, "#000000")})
        self.assertTrue(self.visible())

    def test_empty_or_blank_input_does_not_stop_the_blinking(self):
        self.choose("Playlists", "set_playlist_settings")

        for blank in ("\n", "  \r\n \t"):
            with self.subTest(blank=repr(blank)):
                self.app.save_data_from_text_box(blank)
                self.assertIsNotNone(self.app._blink_id)

    def test_blinks_again_when_the_input_is_gone(self):
        self.choose("Playlists", "set_playlist_settings")
        self.app.save_data_from_text_box("Playlist 1\n")
        self.assertIsNone(self.app._blink_id)

        self.choose("Playlists", "create_playlist")  # choosing another action drops the typed input

        self.assertIsNone(self.app._text_box_data)
        self.assertIsNotNone(self.app._blink_id)
        self.assertEqual(self.looks_over(400), {(GREEN.normal, "#000000"), (GREEN_DARK.normal, "#ffffff")})

    def open_input_window(self, act):
        """Clicks the button; `act(window, callback)` plays the user's part while the input window is open."""
        def fake_window(master, callback):
            window = tk.Toplevel(master)
            master.after(40, lambda: act(window, callback))
            return window

        self.choose("Playlists", "set_playlist_settings")
        with patch.object(gui, "InputTextBox", fake_window):
            self.app._generate_textbox()
        self.app.update()

    def test_does_not_blink_while_the_input_window_is_open(self):
        seen = {}

        def act(window, callback):
            seen["blink_timer"] = self.app._blink_id
            seen["looks"] = self.looks_over(200)  # several blink intervals
            window.destroy()

        self.open_input_window(act)

        self.assertIsNone(seen["blink_timer"])
        self.assertEqual(seen["looks"], {(GREEN.normal, "#000000")})

    def test_blinks_again_when_the_window_is_closed_without_input(self):
        self.open_input_window(lambda window, callback: window.destroy())

        self.assertIsNotNone(self.app._blink_id)
        self.assertEqual(self.looks_over(400), {(GREEN.normal, "#000000"), (GREEN_DARK.normal, "#ffffff")})

    def test_stays_steady_when_the_window_is_closed_after_saving_input(self):
        seen = {}

        def act(window, callback):
            callback("Playlist 1\n")  # what Save does before it closes the window
            seen["blink_timer_after_save"] = self.app._blink_id
            window.destroy()

        self.open_input_window(act)

        self.assertIsNone(seen["blink_timer_after_save"])
        self.assertIsNone(self.app._blink_id)
        self.assertEqual(self.looks_over(150), {(GREEN.normal, "#000000")})

    def test_saving_blank_input_does_not_blink_before_the_window_closes_but_after(self):
        seen = {}

        def act(window, callback):
            callback("\n")
            seen["blink_timer_after_save"] = self.app._blink_id
            window.destroy()

        self.open_input_window(act)

        self.assertIsNone(seen["blink_timer_after_save"])
        self.assertIsNotNone(self.app._blink_id)

    def test_the_window_flag_is_reset_even_when_opening_the_window_fails(self):
        self.choose("Playlists", "set_playlist_settings")

        with patch.object(gui, "InputTextBox", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.app._generate_textbox()

        self.assertFalse(self.app._input_window_open)
        self.assertIsNotNone(self.app._blink_id)

    def test_creating_without_input_is_refused_like_the_other_changing_actions(self):
        with patch("gui_app.gui.messagebox.showinfo") as info, \
                patch.object(self.app, "open_action_log_box") as open_box:
            self.app.perform_create_action("create_playlist", "https://x.example.com", "login", "pw", None)
            self.assertEqual(info.call_count, 1)
            open_box.assert_not_called()

            self.app.perform_create_action("create_playlist", "https://x.example.com", "login", "pw", "Playlist 1")
            open_box.assert_called_once()


if __name__ == "__main__":
    unittest.main()
