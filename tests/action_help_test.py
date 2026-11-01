"""Resting the pointer on an action in the list of actions shows what it does, in a floating window to the right of the
pointer. The texts are in assets/action_descriptions.json, which tools/generate_documentation.py writes from the
descriptions of the user guide, so the help and the guide never say different things."""
import json
import os
import sys
import time
import tkinter as tk
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import generate_documentation as generator  # noqa: E402

from gui_app.tooltip import MAX_VISIBLE_MS, ListTooltip  # noqa: E402
from main_buttons_test import MainWindowCase  # noqa: E402
from util import action_descriptions  # noqa: E402
from util.actions import entity_actions  # noqa: E402


class DescriptionsTest(unittest.TestCase):
    def test_the_file_is_what_the_generator_makes_now(self):
        with open(os.path.join(ROOT, "assets", "action_descriptions.json"), encoding="utf-8") as file:
            self.assertEqual(json.load(file), generator.action_descriptions(),
                             "run: python tools/generate_documentation.py")

    def test_every_action_of_the_window_has_a_description_in_both_languages(self):
        with open(os.path.join(ROOT, "assets", "messages.json"), encoding="utf-8") as file:
            messages = json.load(file)
        for language in ("cz", "en"):
            for category, actions in entity_actions(messages[language]["actions"]).items():
                for key in actions.values():
                    with self.subTest(language=language, action=key):
                        self.assertTrue(action_descriptions.describe(key, language).strip())

    def test_an_unknown_action_or_language_has_none(self):
        self.assertEqual(action_descriptions.describe("no_such_action", "cz"), "")
        self.assertEqual(action_descriptions.describe("get_group_unused", "xx"), "")

    def test_the_two_playlist_actions_of_a_group_say_which_replaces_and_which_adds(self):
        replaces = action_descriptions.describe("set_detailed_playlists_to_groups", "cz")
        adds = action_descriptions.describe("set_add_detailed_playlist_to_group", "cz")
        self.assertIn("nahradí", replaces)
        self.assertIn("zůstanou", adds)


class ListTooltipTest(unittest.TestCase):
    """
    The pointer is looked for, not waited for: the list of a drop-down is open under a grab, and its pointer events do not
    reach a binding reliably. So the tests move the pointer by changing what the list is told about it, and send no events.
    """

    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display available")
        self.addCleanup(self.root.destroy)
        poll = patch("gui_app.tooltip.POINTER_POLL_MS", 10)
        poll.start()
        self.addCleanup(poll.stop)
        self.listbox = tk.Listbox(self.root, height=4)
        for entry in ("one", "two", "three", "four"):
            self.listbox.insert(tk.END, entry)
        self.listbox.pack()
        self.pointer = (-1, -1)
        self.listbox.winfo_pointerxy = lambda: self.pointer
        self.tooltip = ListTooltip(self.listbox, lambda index: f"about entry {index}", delay_ms=60)
        self.root.update()
        self.tooltip.watch()

    def wait(self, milliseconds):
        end = time.monotonic() + milliseconds / 1000
        while time.monotonic() < end:
            self.root.update()
            time.sleep(0.005)

    def point_at(self, index):
        x, y, width, height = self.listbox.bbox(index)
        self.pointer = (self.listbox.winfo_rootx() + x + 5, self.listbox.winfo_rooty() + y + height // 2)

    def shown(self):
        window = self.tooltip._window
        return window.state() == "normal" and self.tooltip._label.cget("text") if window is not None else None

    def test_the_help_of_the_entry_under_the_pointer_appears_after_the_delay(self):
        self.point_at(1)
        self.wait(30)
        self.assertFalse(self.shown())

        self.wait(250)

        self.assertEqual(self.shown(), "about entry 1")

    def test_moving_to_another_entry_hides_it_and_shows_the_help_of_the_new_one(self):
        self.point_at(1)
        self.wait(250)
        self.assertEqual(self.shown(), "about entry 1")

        self.point_at(2)
        self.wait(30)
        self.assertFalse(self.shown())
        self.wait(250)

        self.assertEqual(self.shown(), "about entry 2")

    def test_moving_inside_the_same_entry_does_not_start_over(self):
        self.point_at(1)
        self.wait(250)
        self.assertEqual(self.shown(), "about entry 1")

        x, y = self.pointer
        self.pointer = (x + 3, y)
        self.wait(60)

        self.assertEqual(self.shown(), "about entry 1")

    def test_leaving_the_list_hides_it(self):
        self.point_at(1)
        self.wait(250)
        self.assertTrue(self.shown())

        self.pointer = (-1, -1)
        self.wait(60)

        self.assertFalse(self.shown())

    def test_it_is_shown_to_the_right_of_the_pointer(self):
        self.point_at(1)
        self.wait(250)

        self.assertGreaterEqual(self.tooltip._window.winfo_rootx(), self.pointer[0])

    def test_an_entry_without_a_description_shows_nothing(self):
        self.tooltip._text_of = lambda index: ""
        self.point_at(1)
        self.wait(250)

        self.assertFalse(self.shown())

    def test_it_stays_long_enough_to_be_read(self):
        self.assertGreater(self.tooltip._max_visible_ms, MAX_VISIBLE_MS)

    def test_the_pointer_is_followed_only_while_the_list_is_on_the_screen(self):
        self.assertIsNotNone(self.tooltip._poll_id)

        self.listbox.pack_forget()
        self.wait(100)

        self.assertIsNone(self.tooltip._poll_id)
        self.assertIsNone(self.tooltip._index)

    def test_watching_twice_does_not_follow_the_pointer_twice(self):
        first = self.tooltip._poll_id
        self.tooltip.watch()

        self.assertEqual(self.tooltip._poll_id, first)


class ActionListHelpTest(MainWindowCase):
    def test_the_text_of_an_entry_is_the_description_of_its_action_in_the_language_of_the_window(self):
        self.app.entity_type_var.set("Groups")
        self.app.update_action_selection()
        labels = list(self.app.option_choose_action["values"])
        for language in ("cz", "en"):
            self.app.lang.set_language(language)
            self.app.entity_actions = self.app.load_actions()
            self.app.update_action_selection()
            for index, label in enumerate(self.app.option_choose_action["values"]):
                action = self.app.entity_actions["Groups"][label]
                with self.subTest(language=language, action=action):
                    self.assertEqual(self.app._action_description(index), action_descriptions.describe(action, language))
        self.assertTrue(labels)

    def test_opening_the_list_starts_following_the_pointer_and_closing_it_stops(self):
        box = self.app.option_choose_action
        self.app.entity_type_var.set("Groups")
        self.app.update_action_selection()
        help_ = self.app._action_list_help

        self.app.tk.call("ttk::combobox::Post", box)
        self.addCleanup(self.app.tk.call, "ttk::combobox::Unpost", box)
        deadline = time.monotonic() + 2
        while help_._poll_id is None and time.monotonic() < deadline:
            self.app.update()
            time.sleep(0.01)
        self.assertIsNotNone(help_._poll_id)

        self.app.tk.call("ttk::combobox::Unpost", box)
        deadline = time.monotonic() + 2
        while help_._poll_id is not None and time.monotonic() < deadline:
            self.app.update()
            time.sleep(0.01)
        self.assertIsNone(help_._poll_id)

    def test_an_entry_that_is_not_there_has_no_text(self):
        self.app.entity_type_var.set("Groups")
        self.app.update_action_selection()
        self.assertEqual(self.app._action_description(-1), "")
        self.assertEqual(self.app._action_description(999), "")


if __name__ == "__main__":
    unittest.main()
