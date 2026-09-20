import json
import os
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from gui_app import gui
from gui_app.gui import DSMediaplayApp
from gui_app.input_box import InputTextBox
from itertools import combinations

from processor.csv_generator import convert_days_of_week_to_str
from processor.input_processing import DAY_CODES, convert_days_of_week_to_int, split_list
from util.actions import action_needs_input
from util.input_templates import LANGUAGES, build_template, has_template, strip_template, template_lines

ACTION = "set_group_settings"


class TemplateTextTest(unittest.TestCase):
    def test_the_description_is_made_of_comment_lines_followed_by_one_example_line(self):
        for language in LANGUAGES:
            with self.subTest(language=language):
                lines = template_lines(ACTION, language)

                self.assertTrue(all(line.startswith("# ") for line in lines[:-1]))
                self.assertFalse(lines[-1].startswith("#"))
                self.assertEqual(lines[-1].count("\t"), 9)  # 10 columns

    def test_the_built_template_ends_with_a_line_break(self):
        self.assertTrue(build_template(ACTION, "cz").endswith("\n"))

    def test_cells_with_a_format_show_a_concrete_pattern(self):
        example = template_lines("set_detailed_playlists_to_groups", "cz")[-1].split("\t")

        self.assertIn("31.12.2026", example)
        self.assertIn("08:00", example)
        self.assertIn("mo,tu,we,th,fr", example)

    def test_names_are_placeholders(self):
        for action in ("create_group", "set_group_rename", "set_groups_to_players"):
            with self.subTest(action=action):
                self.assertIn("<", template_lines(action, "cz")[-1])
                self.assertIn("<", template_lines(action, "en")[-1])


class StripTemplateTest(unittest.TestCase):
    def test_an_unchanged_template_is_removed_completely(self):
        for language in LANGUAGES:
            with self.subTest(language=language):
                self.assertEqual(strip_template(build_template(ACTION, language), ACTION).strip(), "")

    def test_a_template_of_the_other_language_is_removed_too(self):
        self.assertEqual(strip_template(build_template(ACTION, "en"), ACTION).strip(), "")
        self.assertEqual(strip_template(build_template(ACTION, "cz"), ACTION).strip(), "")

    def test_user_data_is_kept_above_and_below_the_template(self):
        text = "Group A\t1080p\n" + build_template(ACTION, "cz") + "Group B\t720p"

        self.assertEqual([line for line in strip_template(text, ACTION).split("\n") if line],
                         ["Group A\t1080p", "Group B\t720p"])

    def test_windows_line_endings_are_handled(self):
        text = build_template(ACTION, "cz").replace("\n", "\r\n") + "Group B\t720p"

        self.assertEqual(strip_template(text, ACTION).replace("\r", "").strip(), "Group B\t720p")

    def test_an_edited_example_line_is_data_and_is_kept(self):
        edited = template_lines(ACTION, "cz")[-1].replace("<název skupiny>", "Shop 1")

        self.assertEqual(strip_template(edited, ACTION), edited)

    def test_the_user_own_comment_like_lines_are_data(self):
        self.assertEqual(strip_template("# my own note\tx", ACTION), "# my own note\tx")

    def test_an_action_without_a_template_is_left_alone(self):
        self.assertEqual(strip_template("anything", "get_playlist_details"), "anything")


class DayCodesTest(unittest.TestCase):
    def test_all_seven_days_are_available_as_the_api_numbers_them(self):
        # API: weekdays 1 = Sunday ... 7 = Saturday
        self.assertEqual(convert_days_of_week_to_int(split_list("su,mo,tu,we,th,fr,sa")), [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(convert_days_of_week_to_int(split_list("1,2,3,4,5,6,7")), [1, 2, 3, 4, 5, 6, 7])

    def test_the_older_code_for_saturday_still_works(self):
        self.assertEqual(DAY_CODES["st"], DAY_CODES["sa"])
        self.assertEqual(convert_days_of_week_to_int(split_list("st")), [7])

    def test_the_export_writes_saturday_as_sa_like_the_api_days_and_the_input(self):
        self.assertEqual(convert_days_of_week_to_str([7]), ["sa"])
        self.assertEqual(convert_days_of_week_to_str([1, 2, 3, 4, 5, 6, 7]),
                         ["su", "mo", "tu", "we", "th", "fr", "sa"])

    def test_days_exported_and_pasted_back_mean_the_same_days_for_every_combination(self):
        for size in range(1, 8):
            for days in combinations(range(1, 8), size):
                exported = ", ".join(code.capitalize() for code in convert_days_of_week_to_str(list(days)))
                with self.subTest(days=days):
                    self.assertEqual(convert_days_of_week_to_int(split_list(exported)), list(days))

    def test_older_exports_with_st_still_paste_back_as_saturday(self):
        self.assertEqual(convert_days_of_week_to_int(split_list("Su, Mo, St")), [1, 2, 7])

    def test_unknown_days_are_still_rejected(self):
        for text in ("xx", "0", "8", "mon"):
            with self.subTest(text=text):
                self.assertEqual(convert_days_of_week_to_int(split_list(text)), [8])


class MenuTemplatesTest(unittest.TestCase):
    """The templates and the menu must not drift apart."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        path = os.path.join(self.directory.name, "logins.json")
        with open(path, "w", encoding="utf-8") as file:
            json.dump({"lang": "cz", "font": ["Helvetica", 12], "default": ["", ""], "logins": {}}, file)
        try:
            self.app = DSMediaplayApp(path)
        except tk.TclError:
            self.skipTest("no display available")
        self.actions = {key for actions in self.app.entity_actions.values() for key in actions.values()}

    def tearDown(self):
        if hasattr(self, "app"):
            self.app.destroy()
        self.directory.cleanup()

    def test_every_action_that_needs_input_has_a_template_in_both_languages(self):
        missing = [action for action in sorted(self.actions) if action_needs_input(action) and not has_template(action)]

        self.assertEqual(missing, [])

    def test_no_template_exists_for_an_action_that_needs_no_input_or_is_not_in_the_menu(self):
        from util.input_templates import _templates
        orphans = [action for action in _templates()["cz"]["actions"]
                   if action not in self.actions or not action_needs_input(action)]

        self.assertEqual(orphans, [])

    def test_the_removed_actions_are_not_in_the_menu(self):
        self.assertNotIn("set_clone_player", self.actions)
        self.assertNotIn("set_player_update", self.actions)

    def test_every_template_is_complete_in_both_languages(self):
        for action in sorted(self.actions):
            if not action_needs_input(action):
                continue
            for language in LANGUAGES:
                with self.subTest(action=action, language=language):
                    lines = template_lines(action, language)
                    self.assertGreaterEqual(len(lines), 6)
                    self.assertTrue(lines[-1].strip())
                    self.assertTrue(all(line.strip() for line in lines))


class InputWindowTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        path = os.path.join(self.directory.name, "logins.json")
        with open(path, "w", encoding="utf-8") as file:
            json.dump({"lang": "cz", "font": ["Helvetica", 12], "default": ["", ""], "logins": {}}, file)
        try:
            self.app = DSMediaplayApp(path)
        except tk.TclError:
            self.skipTest("no display available")
        self.app.entity_type_var.set("Groups")
        self.app.update_action_selection()
        label = next(label for label, key in self.app.entity_actions["Groups"].items() if key == ACTION)
        self.app.option_choose_action.set(label)
        self.app.reset_data()
        self.app.update()

    def tearDown(self):
        if hasattr(self, "app"):
            self.app.destroy()
        self.directory.cleanup()

    def window(self):
        return InputTextBox(self.app, self.app.save_data_from_text_box)

    def test_the_button_inserts_the_template_into_the_text(self):
        window = self.window()

        window.insert_template()

        text = window.details_text.get("1.0", tk.END)
        self.assertEqual(text.strip("\n").split("\n")[-1], template_lines(ACTION, "cz")[-1])
        self.assertTrue(text.startswith("# Vzor vstupu"))
        window.destroy()

    def test_it_follows_the_language_of_the_application(self):
        self.app.lang.set_language("en")
        window = self.window()

        window.insert_template()

        self.assertTrue(window.details_text.get("1.0", tk.END).startswith("# Input template"))
        window.destroy()

    def test_clicking_twice_does_not_insert_it_twice(self):
        window = self.window()

        window.insert_template()
        window.insert_template()

        self.assertEqual(window.details_text.get("1.0", tk.END).count("# Vzor vstupu"), 1)
        window.destroy()

    def test_the_description_is_greyed_out_but_the_example_line_is_not(self):
        window = self.window()

        window.insert_template()

        self.assertIn("template", window.details_text.tag_names("1.0"))
        example_line = len(template_lines(ACTION, "cz"))  # the last line of the template
        self.assertNotIn("template", window.details_text.tag_names(f"{example_line}.0"))
        self.assertIn("template", window.details_text.tag_names(f"{example_line - 1}.0"))
        window.destroy()

    def test_saving_only_the_template_leaves_no_input(self):
        window = self.window()
        window.insert_template()

        window.save_text()  # what the Save button does

        self.assertEqual(self.app._text_box_data.strip(), "")
        self.assertFalse(self.app.has_input())

    def test_saving_the_template_with_data_keeps_only_the_data(self):
        window = self.window()
        window.insert_template()
        window.details_text.insert(tk.END, "Group 1\t1080p\tlandscape\n")

        window.save_text()

        self.assertEqual(self.app._text_box_data.strip(), "Group 1\t1080p\tlandscape")
        self.assertTrue(self.app.has_input())

    def test_running_with_only_the_template_is_refused_like_running_without_input(self):
        window = self.window()
        window.insert_template()
        window.save_text()

        with patch("gui_app.gui.messagebox.showinfo") as info, patch.object(self.app, "open_action_log_box") as box:
            self.app.perform_set_action(ACTION, "https://x.example.com", "login", "pw", self.app._text_box_data)

            self.assertEqual(info.call_count, 1)
            box.assert_not_called()

    def test_blank_input_is_missing_for_every_kind_of_changing_action(self):
        for handler, action in ((self.app.perform_set_action, ACTION),
                                (self.app.perform_remove_action, "remove_unused_groups"),
                                (self.app.perform_create_action, "create_group")):
            for data in (None, "", "  \n\t \n"):
                with self.subTest(handler=handler.__name__, data=data):
                    with patch("gui_app.gui.messagebox.showinfo") as info, \
                            patch.object(self.app, "open_action_log_box") as box:
                        handler(action, "https://x.example.com", "login", "pw", data)

                        self.assertEqual(info.call_count, 1)
                        box.assert_not_called()

    def test_the_button_reports_an_action_without_a_template(self):
        self.app.entity_type_var.set("Groups")
        label = next(label for label, key in self.app.entity_actions["Groups"].items()
                     if key == "get_group_settings")
        self.app.option_choose_action.set(label)
        window = self.window()

        with patch("gui_app.input_box.messagebox.showinfo") as info:
            window.insert_template()

        self.assertEqual(info.call_count, 1)
        self.assertEqual(window.details_text.get("1.0", tk.END).strip(), "")
        window.destroy()


if __name__ == "__main__":
    unittest.main()
