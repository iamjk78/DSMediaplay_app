"""The list of actions tints its entries by what they do: the CSV exports light green, removing and deleting light red,
everything else (setting, adding, renaming, creating, the snapshots, deploying) light blue."""
import unittest

from gui_app import gui
from gui_app.color_button import BLUE, GREEN, RED
from main_buttons_test import MainWindowCase
from util.actions import action_kind, entity_actions

TINTS = {"read": GREEN.normal, "change": BLUE.normal, "remove": RED.normal}


class ActionKindTest(unittest.TestCase):
    def test_every_action_is_read_removed_or_changed(self):
        for action, kind in (("get_group_unused", "read"), ("get_player_overview", "read"),
                             ("remove_playlists_from_group", "remove"), ("remove_all_unused_assets", "remove"),
                             ("set_group_rename", "change"), ("set_add_detailed_playlist_to_group", "change"),
                             ("create_group", "change"), ("show_player_snapshots", "change"),
                             ("set_player_snapshot", "change"), ("set_deploy_all_players", "change"),
                             ("set_deploy_selected_groups", "change")):
            with self.subTest(action=action):
                self.assertEqual(action_kind(action), kind)

    def test_a_list_has_its_green_blue_and_red_entries_together_each_block_by_the_alphabet(self):
        import json
        import unicodedata
        from util.paths import resource_path
        with open(resource_path("assets/messages.json"), encoding="utf-8") as file:
            messages = json.load(file)

        def plain(label):  # the alphabet of a label, the accents aside
            return "".join(c for c in unicodedata.normalize("NFD", label) if not unicodedata.combining(c)).casefold()

        for language in ("cz", "en"):
            for category, actions in entity_actions(messages[language]["actions"]).items():
                kinds = [action_kind(key) for key in actions.values()]
                blocks = [kind for i, kind in enumerate(kinds) if i == 0 or kind != kinds[i - 1]]
                self.assertEqual(blocks, sorted(set(blocks), key=("read", "change", "remove").index), (language, category))
                for kind in set(kinds):
                    labels = [plain(label) for label, key in actions.items() if action_kind(key) == kind]
                    self.assertEqual(labels, sorted(labels), (language, category, kind))


class ActionListTintTest(MainWindowCase):
    def posted_colours(self, entity_type):
        """The colours of the entries of the list as it is when opened (it is closed again first, as a choice closes it)."""
        box = self.app.option_choose_action
        self.app.tk.call("ttk::combobox::Unpost", box)
        self.app.entity_type_var.set(entity_type)
        self.app.update_action_selection()
        self.app.tk.call("ttk::combobox::Post", box)
        self.app.update()
        self.addCleanup(self.app.tk.call, "ttk::combobox::Unpost", box)
        listbox = f"{self.app.tk.call('ttk::combobox::PopdownWindow', box)}.f.l"
        actions = self.app.entity_actions[entity_type]
        return {label: str(self.app.tk.call(listbox, "itemcget", index, "-background")) or None
                for index, label in enumerate(box["values"])}, actions

    def test_the_entries_are_tinted_by_what_they_do(self):
        for entity_type in ("Groups", "Players", "Assets", "Deploy"):
            with self.subTest(entity_type=entity_type):
                colours, actions = self.posted_colours(entity_type)
                for label, colour in colours.items():
                    expected = TINTS[action_kind(actions[label])]
                    self.assertEqual(colour, expected, label)
                self.assertNotIn(None, colours.values())

    def test_the_tint_comes_back_every_time_the_list_opens(self):
        for _ in range(2):
            colours, _ = self.posted_colours("Groups")
            self.assertIn(GREEN.normal, colours.values())

    def test_the_default_entry_of_a_category_is_a_reading_one(self):
        for entity_type in ("Playlists", "Groups", "Players", "Locations", "Assets"):
            self.app.entity_type_var.set(entity_type)
            self.app.update_action_selection()
            label = self.app.option_choose_action.get()
            self.assertEqual(action_kind(self.app.entity_actions[entity_type][label]), "read", entity_type)


if __name__ == "__main__":
    unittest.main()
