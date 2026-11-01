"""The application opens with the category and the action of the last use, like it does with the account. A removing
action is not restored: only its category, so that a deleting action is never one click from Start after a restart."""
import json
import unittest
from unittest.mock import patch

from gui_app import gui
from main_buttons_test import MainWindowCase
from util import accounts


class RememberActionTest(unittest.TestCase):
    def test_a_category_and_an_action_are_recorded_and_a_repeat_is_not_a_change(self):
        data = {}

        self.assertTrue(accounts.remember_action(data, "Groups", "set_group_rename"))
        self.assertEqual(data["last_action"], ["Groups", "set_group_rename"])
        self.assertFalse(accounts.remember_action(data, "Groups", "set_group_rename"))

    def test_a_removing_action_is_recorded_as_its_category_only(self):
        for action in ("remove_unused_groups", "remove_all_unused_groups", "remove_playlists_from_group"):
            with self.subTest(action=action):
                data = {"last_action": ["Groups", "set_group_rename"]}
                self.assertTrue(accounts.remember_action(data, "Groups", action))
                self.assertEqual(data["last_action"], ["Groups", ""])

    def test_nothing_is_recorded_without_a_category(self):
        data = {}
        self.assertFalse(accounts.remember_action(data, "", "get_group_unused"))
        self.assertNotIn("last_action", data)

    def test_a_config_edited_into_something_else_gives_no_last_action(self):
        for value in (None, "Groups", ["Groups"], ["Groups", 3], ["a", "b", "c"], {"Groups": "x"}, 7):
            with self.subTest(value=value):
                self.assertEqual(accounts.last_action({"last_action": value}), ("", ""))
        self.assertEqual(accounts.last_action({"last_action": ["Groups", "get_group_unused"]}),
                         ("Groups", "get_group_unused"))


class LastActionWindowTest(MainWindowCase):
    def choose(self, entity_type, action=None):
        self.app.entity_type_var.set(entity_type)
        self.app.on_entity_selected()
        if action:
            self.app.option_choose_action.set(self.label(entity_type, action))
            self.app.on_action_selected()

    def label(self, entity_type, action):
        return next(label for label, key in self.app.entity_actions[entity_type].items() if key == action)

    def default_action(self, entity_type):
        """What a category opens with: the first of its actions, a reading one."""
        return next(iter(self.app.entity_actions[entity_type].values()))

    def restart(self):
        path = self.app.config_file
        self.app.destroy()
        self.app = gui.DSMediaplayApp(path)
        self.addCleanup(self.close_app)
        self.app.update()

    def stored(self):
        with open(self.app.config_file, encoding="utf-8") as file:
            return json.load(file).get("last_action")

    def test_the_next_start_opens_the_category_and_the_action_of_the_last_use(self):
        self.choose("Groups", "set_group_rename")

        self.restart()

        self.assertEqual(self.app.entity_type_var.get(), "Groups")
        self.assertEqual(self.app.option_choose_action.get(), self.label("Groups", "set_group_rename"))
        self.assertEqual(self.app.current_action(), "set_group_rename")

    def test_a_removing_action_comes_back_as_its_category_with_the_default_action(self):
        self.choose("Groups", "remove_unused_groups")
        self.assertEqual(self.stored(), ["Groups", ""])

        self.restart()

        self.assertEqual(self.app.entity_type_var.get(), "Groups")
        self.assertEqual(self.app.current_action(), self.default_action("Groups"))

    def test_choosing_only_a_category_remembers_its_default_action(self):
        self.choose("Assets")

        self.assertEqual(self.stored(), ["Assets", self.default_action("Assets")])

    def test_without_anything_remembered_nothing_is_selected(self):
        self.assertEqual((self.app.entity_type_var.get(), self.app.option_choose_action.get()), ("", ""))

    def test_an_action_that_is_gone_or_a_hand_edited_value_opens_the_category_with_the_default(self):
        for value in (["Groups", "no_such_action"], ["Nowhere", "get_group_unused"], "junk"):
            with self.subTest(value=value):
                self.app.all_data["last_action"] = value
                self.app.save_account_configs()

                self.restart()

                self.assertEqual(self.app.entity_type_var.get(), value[0] if value[0] == "Groups" and len(value) == 2 else "")
                if self.app.entity_type_var.get():
                    self.assertEqual(self.app.current_action(), self.default_action("Groups"))

    def test_a_removing_action_in_the_file_is_not_restored_either(self):
        self.app.all_data["last_action"] = ["Groups", "remove_all_unused_groups"]
        self.app.save_account_configs()

        self.restart()

        self.assertEqual(self.app.current_action(), self.default_action("Groups"))

    def test_the_account_and_the_last_action_do_not_overwrite_each_other(self):
        self.choose("Playlists", "create_playlist")
        self.app.option_choose_administration.set("Demo")
        self.app.on_account_selected()

        with open(self.app.config_file, encoding="utf-8") as file:
            config = json.load(file)
        self.assertEqual(config["last_action"], ["Playlists", "create_playlist"])
        self.assertEqual(config["default"][0], "Demo")


if __name__ == "__main__":
    unittest.main()
