"""A turn of the mouse wheel scrolls the same way up and down, and what the server calls a player never breaks a row."""
import unittest

from gui_app.wheel import wheel_units
from util.player_filter import player_row


class WheelTest(unittest.TestCase):
    def test_windows_scrolls_up_and_down_by_the_same_amount_for_every_size_of_step(self):
        for delta in (120, 240, 360, 40, 20, 1, 119, 121):
            with self.subTest(delta=delta):
                self.assertEqual(wheel_units(delta, aqua=False), -wheel_units(-delta, aqua=False))
                self.assertNotEqual(wheel_units(delta, aqua=False), 0)
                self.assertLess(wheel_units(delta, aqua=False), 0)  # a positive delta is up: a negative number of lines

    def test_a_wheel_notch_is_one_line_per_120_and_no_step_is_nothing(self):
        self.assertEqual(wheel_units(120, False), -1)
        self.assertEqual(wheel_units(-240, False), 2)
        self.assertEqual(wheel_units(0, False), 0)

    def test_macos_reports_lines_already(self):
        self.assertEqual(wheel_units(3, True), -3)
        self.assertEqual(wheel_units(-2, True), 2)


class PlayerRowNamesTest(unittest.TestCase):
    def test_line_breaks_and_double_spaces_in_names_are_one_space(self):
        row = player_row({"name": "Lobby\nPraha\r\n 1", "group": {"name": "Shop\n2"}, "configLocation": "Hall\t3"})

        self.assertEqual((row.name, row.group, row.location), ("Lobby Praha 1", "Shop 2", "Hall 3"))

    def test_a_missing_or_null_name_is_empty_not_an_error(self):
        for player in ({}, {"name": None}, {"name": None, "group": None, "configLocation": None}):
            with self.subTest(player=player):
                self.assertEqual(player_row(player).name, "")


if __name__ == "__main__":
    unittest.main()
