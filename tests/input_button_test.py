import json
import os
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from gui_app.gui import DSMediaplayApp
from util.actions import action_needs_input


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
