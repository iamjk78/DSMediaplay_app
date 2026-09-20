import json
import os
import tkinter as tk
import unittest
from tkinter import font as tkfont
from tkinter import ttk
from unittest.mock import MagicMock, patch

from gui_app.player_browser import (BUTTON_STYLE, CHECK_STYLE, COLUMNS, LARGE_A_STYLE, MAX_FONT_SIZE, MIN_FONT_SIZE,
                                    SMALL_A_STYLE, SNAPSHOT_COLUMN_MINSIZE, valid_font_size)
from player_browser_test import BrowserTestCase, PLAYERS


class FontSizeCase(BrowserTestCase):
    def points(self, widget):
        return tkfont.Font(root=self.app, font=widget.cget("font")).actual()["size"]

    def style_points(self, style):
        return tkfont.Font(root=self.app, font=ttk.Style(self.app).lookup(style, "font")).actual()["size"]

    def cells(self, browser):
        return [cell for widgets in browser._widgets.values() for cell in widgets[1:]]

    def aligned(self, browser):
        self.app.update()
        first_row = browser._widgets[id(browser._visible[0])]
        for index, (key, _, _) in enumerate(COLUMNS):
            header, widget = browser._header_cells[key], browser._filter_widgets[key]
            if header.winfo_ismapped():
                self.assertEqual((widget.winfo_rootx(), widget.winfo_width()), (header.winfo_rootx(), header.winfo_width()), key)
                self.assertEqual(first_row[index + 1].winfo_rootx(), header.winfo_rootx(), key)


class FontButtonsTest(FontSizeCase):
    def test_a_small_and_a_large_a_are_in_the_free_place_above_the_first_screenshot_button(self):
        browser = self.open()
        self.app.update()

        smaller, larger = browser.smaller_font_button, browser.larger_font_button
        self.assertEqual((smaller.cget("text"), larger.cget("text")), ("A", "A"))
        self.assertLess(smaller.winfo_rootx(), larger.winfo_rootx())
        for button in (smaller, larger):
            self.assertLess(button.winfo_rooty() + button.winfo_height(), browser._header_cells["name"].winfo_rooty())
            self.assertGreaterEqual(button.winfo_rootx(), browser._body.winfo_rootx())  # inside the first column
            self.assertLess(button.winfo_rootx() + button.winfo_width(), browser._header_cells["name"].winfo_rootx())
        self.assertLess(self.style_points(SMALL_A_STYLE), self.style_points(LARGE_A_STYLE))

    def test_they_are_narrow_enough_not_to_move_the_filters(self):
        browser = self.open()
        self.app.update()

        self.assertLessEqual(browser._font_holder.winfo_reqwidth(), SNAPSHOT_COLUMN_MINSIZE - 8)
        self.assertEqual(browser._first_width, SNAPSHOT_COLUMN_MINSIZE)  # the column is as narrow as it was
        self.aligned(browser)

    def test_the_two_a_buttons_keep_their_own_size_whatever_the_size_of_the_text(self):
        browser = self.open()
        small, large = self.style_points(SMALL_A_STYLE), self.style_points(LARGE_A_STYLE)

        for _ in range(5):
            browser.larger_font_button.invoke()

        self.assertEqual((self.style_points(SMALL_A_STYLE), self.style_points(LARGE_A_STYLE)), (small, large))

    def test_they_have_tooltips_that_say_the_current_size(self):
        browser = self.open()

        self.assertIn("12", browser.smaller_font_button.tooltip._text())
        self.assertIn("Zmenšit", browser.smaller_font_button.tooltip._text())
        self.assertIn("Zvětšit", browser.larger_font_button.tooltip._text())
        browser.larger_font_button.invoke()
        self.assertIn("13", browser.larger_font_button.tooltip._text())

    def test_both_are_on_at_first_and_the_one_at_a_limit_is_off(self):
        browser = self.open()
        self.assertTrue(browser.smaller_font_button.instate(["!disabled"]))
        self.assertTrue(browser.larger_font_button.instate(["!disabled"]))

        browser.set_font_size(MAX_FONT_SIZE)
        self.assertTrue(browser.larger_font_button.instate(["disabled"]))
        self.assertTrue(browser.smaller_font_button.instate(["!disabled"]))
        browser.set_font_size(MIN_FONT_SIZE)
        self.assertTrue(browser.smaller_font_button.instate(["disabled"]))
        self.assertTrue(browser.larger_font_button.instate(["!disabled"]))


class FontSizeTest(FontSizeCase):
    def test_it_starts_with_the_font_of_the_main_window_or_the_saved_size(self):
        self.assertEqual(self.open().font_size, 12)
        self.assertEqual(self.open(font_size=15).font_size, 15)

    def test_a_saved_size_that_makes_no_sense_is_ignored(self):
        for raw in (None, 5, 21, 99, -3, "14", 12.5, True, [12]):
            with self.subTest(raw=raw):
                self.assertIsNone(valid_font_size(raw))
                self.assertEqual(self.open(font_size=raw).font_size, 12)
        self.assertEqual((valid_font_size(8), valid_font_size(20)), (8, 20))

    def test_a_main_window_font_outside_the_range_is_brought_into_it(self):
        self.app.font = ("Helvetica", 30)
        self.assertEqual(self.open().font_size, MAX_FONT_SIZE)
        self.app.font = ("Helvetica", 4)
        self.assertEqual(self.open().font_size, MIN_FONT_SIZE)

    def test_the_large_a_makes_everything_one_point_larger_and_the_small_a_smaller(self):
        saved = []
        browser = self.open(save_font_size=saved.append)

        browser.larger_font_button.invoke()
        browser.larger_font_button.invoke()
        browser.smaller_font_button.invoke()

        self.assertEqual(browser.font_size, 13)
        self.assertEqual(saved, [13, 14, 13])

    def test_the_rows_the_header_the_filters_and_the_buttons_all_follow(self):
        browser = self.open()

        browser.set_font_size(16)
        self.app.update()

        self.assertTrue(all(self.points(cell) == 16 for cell in self.cells(browser)))
        self.assertTrue(all(self.points(cell) == 16 for cell in browser._header_cells.values()))
        self.assertTrue(all("bold" in str(cell.cget("font")).lower() or tkfont.Font(root=self.app, font=cell.cget("font")).actual()["weight"] == "bold"
                            for cell in browser._header_cells.values()))
        for widget in (browser.name_entry, browser.note_entry, browser.status_box, browser.synced_box,
                       browser.reported_box, browser.group_box.entry, browser.location_box.entry,
                       browser.label_box.entry, browser._status_label, browser._updated_label,
                       browser._columns_label, *browser.column_buttons.values()):
            self.assertEqual(self.points(widget), 16, str(widget))
        self.assertEqual(self.style_points(BUTTON_STYLE), 16)  # Update, Reset, Default columns and the screenshot buttons
        self.assertEqual(self.style_points(CHECK_STYLE), 16)  # the check boxes of the lists

    def test_the_text_size_makes_the_rows_higher_and_the_header_and_the_filters_follow(self):
        browser = self.open()
        self.app.update()
        row, header, filters = (browser._widgets[id(browser._visible[0])][1].winfo_height(),
                                browser._header_canvas.winfo_reqheight(), browser._filter_canvas.winfo_reqheight())

        browser.set_font_size(20)
        self.app.update()

        self.assertGreater(browser._widgets[id(browser._visible[0])][1].winfo_height(), row)
        self.assertEqual(browser._header_canvas.winfo_reqheight(), browser._header.winfo_reqheight())
        self.assertGreater(browser._header_canvas.winfo_reqheight(), header)
        self.assertGreaterEqual(browser._filter_canvas.winfo_reqheight(), filters)
        self.assertEqual(browser._filter_canvas.winfo_reqheight(), browser._filters.winfo_reqheight())

    def test_the_filters_stay_above_their_columns_and_the_rows_under_the_header_at_every_size(self):
        browser = self.open()

        for size in (8, 9, 12, 16, 20, 14):
            with self.subTest(size=size):
                browser.set_font_size(size)
                self.aligned(browser)

    def test_the_first_column_grows_only_when_the_screenshot_buttons_need_it(self):
        browser = self.open()
        self.app.update()
        self.assertEqual(browser._first_width, SNAPSHOT_COLUMN_MINSIZE)

        browser.set_font_size(MAX_FONT_SIZE)
        self.app.update()

        button = browser._widgets[id(browser._visible[0])][0]
        self.assertGreaterEqual(browser._first_width, button.winfo_reqwidth() + 8)
        self.assertLessEqual(button.winfo_width(), browser._first_width)
        self.aligned(browser)

    def test_a_limit_press_does_nothing_and_saves_nothing(self):
        saved = []
        browser = self.open(font_size=MAX_FONT_SIZE, save_font_size=saved.append)

        browser.change_font_size(1)
        browser.larger_font_button.invoke()

        self.assertEqual((browser.font_size, saved), (MAX_FONT_SIZE, []))

    def test_many_presses_reach_the_limits_and_stop_there(self):
        browser = self.open()

        for _ in range(30):
            browser.change_font_size(1)
        self.assertEqual(browser.font_size, MAX_FONT_SIZE)
        for _ in range(30):
            browser.change_font_size(-1)
        self.assertEqual(browser.font_size, MIN_FONT_SIZE)

    def test_rows_that_come_later_have_the_size_too(self):
        fetch = MagicMock(return_value=PLAYERS)
        browser = self.open(fetch)
        browser.set_font_size(17)
        self.advance(browser, 11)

        browser.refresh()
        self.wait_for(lambda: not browser._loading)

        self.assertTrue(all(self.points(cell) == 17 for cell in self.cells(browser)))

    def test_the_hidden_columns_the_filters_and_the_sort_are_not_touched(self):
        browser = self.open(hidden_columns=["note"])
        browser._header_cells["reported"].event_generate("<ButtonPress-1>", x=2, y=2, rootx=5000, rooty=10)
        self.type_into(browser, browser.name_var, "prerov")
        names = browser.visible_names()

        browser.set_font_size(18)
        self.app.update()

        self.assertEqual((browser.hidden_columns(), browser._sort, browser.visible_names(), browser.name_var.get()),
                         (["note"], ("reported", False), names, "prerov"))
        self.assertFalse(browser.note_entry.winfo_ismapped())

    def test_the_minimum_width_of_the_columns_follows_the_text(self):
        browser = self.open()
        small = dict(browser._min_widths)

        browser.set_font_size(20)

        self.assertGreater(browser._min_widths["group"], small["group"])


class FontSizeAndWidthsTest(FontSizeCase):
    def test_widths_that_were_never_set_follow_the_font_by_themselves(self):
        saved = []
        browser = self.open(save_column_widths=saved.append)
        before = browser.column_widths()

        browser.set_font_size(18)

        self.assertEqual(browser.column_widths(), browser._default_widths)
        self.assertTrue(all(browser.column_widths()[key] > before[key] for key in ("name", "location", "note")))
        self.assertEqual(saved, [])  # nothing of the user's is saved: there is nothing of his

    def test_the_widths_the_user_set_follow_the_font_by_ratio_and_are_saved(self):
        saved = []
        browser = self.open(column_widths={"name": 300, "group": 200, "note": 400}, save_column_widths=saved.append)

        browser.set_font_size(18)  # 12 -> 18 is 1.5 times

        widths = browser.column_widths()
        self.assertEqual((widths["name"], widths["group"], widths["note"]), (450, 300, 600))
        self.assertEqual(saved, [widths])
        browser.set_font_size(12)
        self.assertEqual(browser.column_widths()["name"], 300)  # and back again

    def test_a_width_dragged_by_hand_counts_as_set(self):
        saved = []
        browser = self.open(save_column_widths=saved.append)
        self.app.update()
        separator = browser._header_separators[0]
        x = separator.winfo_rootx() + 3
        separator.event_generate("<ButtonPress-1>", x=3, y=5, rootx=x, rooty=100)
        separator.event_generate("<B1-Motion>", x=3, y=5, rootx=x + 40, rooty=100, state=0x100)
        separator.event_generate("<ButtonRelease-1>", x=3, y=5, rootx=x + 40, rooty=100)
        width = browser.column_widths()["name"]
        saved.clear()

        browser.set_font_size(24 if False else 18)

        self.assertEqual(browser.column_widths()["name"], round(width * 1.5))
        self.assertEqual(len(saved), 1)

    def test_default_columns_after_a_change_gives_the_defaults_of_the_current_font(self):
        saved = []
        browser = self.open(column_widths={"name": 300}, save_column_widths=saved.append)
        browser.set_font_size(16)
        saved.clear()

        browser.default_columns_button.invoke()

        self.assertEqual(browser.column_widths(), browser._default_widths)
        self.assertEqual(saved, [{}])
        browser.set_font_size(18)
        self.assertEqual(browser.column_widths(), browser._default_widths)  # and they follow again by themselves

    def test_scaled_widths_never_go_below_what_a_filter_needs(self):
        browser = self.open(column_widths={key: 60 for key, _, _ in COLUMNS})

        browser.set_font_size(MIN_FONT_SIZE)

        for key, _, _ in COLUMNS:
            self.assertGreaterEqual(browser.column_widths()[key], browser._min_widths[key])
            self.assertTrue(browser._filter_widgets[key].winfo_width() >= 30)

    def test_the_window_scroll_state_is_still_right_after_a_change(self):
        browser = self.open()
        self.app.update()

        for size in (20, 8, 12):
            browser.set_font_size(size)
            for _ in range(20):
                self.app.update()
                time.sleep(0.005)
            width = browser._body.winfo_reqwidth()
            self.assertEqual(int(browser._canvas.cget("scrollregion").split()[2]), width)
            if browser._fits("x"):
                self.assertEqual(browser._body.winfo_rootx() - browser._canvas.winfo_rootx(), 0)


class FontSizeStorageTest(FontSizeCase):
    def test_the_main_window_stores_the_size_per_account_next_to_the_widths(self):
        self.app.all_data["logins"]["Demo"] = {"url": "https://x", "names": {"jane": {"login": "jane"}},
                                               "player_font": 15, "player_columns": {"name": 300}}
        self.app.all_data["logins"]["Other"] = {"url": "https://y", "names": {}}
        self.app.account_data = self.app.all_data["logins"]
        self.app.save_account_configs()
        self.app.option_choose_administration.set("Demo")
        with patch("gui_app.gui.PlayerBrowser") as browser_class:
            self.app.open_player_browser("https://x", "jane", "pw")
            options = browser_class.call_args.kwargs

            self.assertEqual(options["font_size"], 15)
            options["save_font_size"](17)

        with open(self.app.config_file, encoding="utf-8") as file:
            saved = json.load(file)["logins"]
        self.assertEqual(saved["Demo"]["player_font"], 17)
        self.assertEqual(saved["Demo"]["player_columns"], {"name": 300})
        self.assertNotIn("player_font", saved["Other"])

    def test_an_account_without_a_saved_size_opens_with_none(self):
        self.app.all_data["logins"]["Demo"] = {"url": "https://x", "names": {}}
        self.app.account_data = self.app.all_data["logins"]
        self.app.save_account_configs()
        self.app.option_choose_administration.set("Demo")
        with patch("gui_app.gui.PlayerBrowser") as browser_class:
            self.app.open_player_browser("https://x", "jane", "pw")

        self.assertIsNone(browser_class.call_args.kwargs["font_size"])

    def test_saving_a_size_for_a_removed_account_writes_nothing(self):
        self.app.save_player_font_size("Gone", 15)

        with open(self.app.config_file, encoding="utf-8") as file:
            self.assertEqual(json.load(file)["logins"], {})

    def test_the_size_is_used_when_the_window_is_opened_again(self):
        saved = []
        first = self.open(save_font_size=saved.append)
        first.set_font_size(15)
        first.destroy()

        second = self.open(font_size=saved[-1])

        self.assertEqual(second.font_size, 15)
        self.assertTrue(all(self.points(cell) == 15 for cell in self.cells(second)))
        self.aligned(second)


import time  # noqa: E402  (used by the scroll test above)

if __name__ == "__main__":
    unittest.main()
