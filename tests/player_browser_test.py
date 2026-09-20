import json
import os
import re
import glob
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

import requests

from api_testing.request_calls import LoginError, ServerApi
from gui_app import gui
from gui_app.player_browser import (COLUMNS, EDGE_ZONE, MAX_COLUMN_WIDTH, MIN_COLUMN_WIDTH, RESIZE_CURSOR,
                                    SEPARATOR_COLOR, SORT_CURSOR, PlayerBrowser, valid_widths)
from util.language import LanguageManager

ACTION = "show_player_snapshots"


def player(name, connected=True, group="Obchod", location="Praha", labels=(), uploaded=0):
    return {"name": name, "isConnected": connected, "group": {"name": group} if group else None,
            "configLocation": location, "labels": list(labels), "lastUpload": uploaded}


PLAYERS = [
    player("Lobby", True, "Kancelar", "Praha", ["vstup"], 1_790_000_000_000),
    player("Prerov 1", False, "Obchod", "Prerov", ["vstup", "test"], 1_780_000_000_000),
    player("Prerov 2", True, "Obchod", "Prerov"),
    player("Sklad", True, None, ""),
]


class BrowserTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        path = os.path.join(self.directory.name, "logins.json")
        with open(path, "w", encoding="utf-8") as file:
            json.dump({"lang": "cz", "font": ["Helvetica", 12], "default": ["", ""], "logins": {}}, file)
        try:
            self.app = gui.DSMediaplayApp(path)
        except tk.TclError:
            self.skipTest("no display available")
        self.addCleanup(self.app.destroy)
        self.app.update()

    def open(self, fetch=None, players=PLAYERS, **options):
        fetch = fetch or MagicMock(return_value=players)
        browser = PlayerBrowser(self.app, url="https://demo.example.com", login="jane", password="pw",
                                account_name="Demo", fetch=fetch, **options)
        self.addCleanup(lambda: browser.winfo_exists() and browser.destroy())
        self.wait_for(lambda: not browser._loading)
        return browser

    def wait_for(self, condition, seconds=5):
        end = time.monotonic() + seconds
        while not condition() and time.monotonic() < end:
            self.app.update()
            time.sleep(0.01)
        self.assertTrue(condition(), "timed out")

    def choose(self, box, text):
        box.set(text)
        box.event_generate("<<ComboboxSelected>>")
        self.app.update()


class PlayerBrowserTest(BrowserTestCase):
    def test_all_players_are_listed_sorted_by_name_with_a_count(self):
        browser = self.open()

        self.assertEqual(browser.visible_names(), ["Lobby", "Prerov 1", "Prerov 2", "Sklad"])
        self.assertEqual(browser.status_var.get(), "Zobrazeno 4 z 4")
        self.assertEqual(browser.title(), "Snímek obrazovky - Demo")

    def test_the_row_shows_state_group_location_and_when_it_was_synced(self):
        browser = self.open()
        cells = {row.name: [w for w in browser._widgets[id(row)]] for row in browser._rows}

        lobby, offline, ungrouped = cells["Lobby"], cells["Prerov 1"], cells["Sklad"]
        self.assertEqual([c.cget("text") for c in lobby[:4]], ["Lobby", "Online", "Kancelar", "Praha"])
        self.assertEqual(offline[1].cget("text"), "Offline")
        self.assertNotEqual(str(lobby[1].cget("foreground")), str(offline[1].cget("foreground")))
        self.assertRegex(lobby[4].cget("text"), r"^\d\d\.\d\d\.\d{4} \d\d:\d\d$")
        self.assertEqual(ungrouped[2].cget("text"), "")
        self.assertEqual(ungrouped[4].cget("text"), "nikdy")

    def test_every_row_has_a_snapshot_button_that_is_inactive_for_now(self):
        browser = self.open()

        buttons = [widgets[-1] for widgets in browser._widgets.values()]
        self.assertEqual(len(buttons), 4)
        for button in buttons:
            self.assertEqual(button.cget("text"), "Snímek")
            self.assertTrue(button.instate(["disabled"]))

    def test_the_name_filter_takes_a_part_of_the_name(self):
        browser = self.open()

        browser.name_var.set("rerov")
        self.wait_for(lambda: browser.visible_names() == ["Prerov 1", "Prerov 2"])
        self.assertEqual(browser.status_var.get(), "Zobrazeno 2 z 4")

    def test_group_category_location_and_state_filters(self):
        browser = self.open()

        self.choose(browser.group_box, "Obchod")
        self.assertEqual(browser.visible_names(), ["Prerov 1", "Prerov 2"])
        self.choose(browser.status_box, "Online")
        self.assertEqual(browser.visible_names(), ["Prerov 2"])
        self.choose(browser.status_box, "(vše)")
        self.choose(browser.label_box, "test")
        self.assertEqual(browser.visible_names(), ["Prerov 1"])
        self.choose(browser.label_box, "(vše)")
        self.choose(browser.group_box, "(vše)")
        self.choose(browser.location_box, "Praha")
        self.assertEqual(browser.visible_names(), ["Lobby"])

    def test_the_drop_downs_offer_what_the_account_has(self):
        browser = self.open()

        self.assertEqual(list(browser.group_box["values"]), ["(vše)", "(bez skupiny)", "Kancelar", "Obchod"])
        self.assertEqual(list(browser.label_box["values"]), ["(vše)", "test", "vstup"])
        self.assertEqual(list(browser.location_box["values"]), ["(vše)", "Praha", "Prerov"])
        self.assertEqual(list(browser.status_box["values"]), ["(vše)", "Online", "Offline"])

    def test_the_players_without_a_group_have_their_own_choice(self):
        browser = self.open()

        self.choose(browser.group_box, "(bez skupiny)")

        self.assertEqual(browser.visible_names(), ["Sklad"])

    def test_no_match_says_so_and_clearing_the_filter_brings_the_players_back(self):
        browser = self.open()

        browser.name_var.set("nic takového")
        self.wait_for(lambda: browser.visible_names() == [])
        self.assertEqual(browser.status_var.get(), "Žádný player neodpovídá filtrům.")
        browser.name_var.set("")
        self.wait_for(lambda: len(browser.visible_names()) == 4)

    def test_an_account_without_players_says_so(self):
        browser = self.open(players=[])

        self.assertEqual(browser.status_var.get(), "Účet nemá žádné playery.")

    def test_clicking_a_header_sorts_and_clicking_again_reverses(self):
        browser = self.open()

        browser._header_cells["name"].event_generate("<Button-1>")
        self.assertEqual(browser.visible_names(), ["Sklad", "Prerov 2", "Prerov 1", "Lobby"])
        self.assertTrue(browser._header_cells["name"].cget("text").endswith("▼"))
        browser._header_cells["status"].event_generate("<Button-1>")
        self.assertEqual(browser.visible_names()[-1], "Prerov 1")  # online first
        self.assertFalse(browser._header_cells["name"].cget("text").endswith(("▼", "▲")))

    def test_the_rows_line_up_under_the_header(self):
        browser = self.open()
        self.app.update()

        first_row = browser._widgets[id(browser._visible[0])]
        for index, (key, _, _) in enumerate(COLUMNS):
            with self.subTest(column=key):
                self.assertEqual(browser._header_cells[key].winfo_x(), first_row[index].winfo_x())

    def test_the_window_is_wide_enough_for_the_table(self):
        browser = self.open()
        self.app.update()

        self.assertGreaterEqual(browser.winfo_width(), browser._header.winfo_reqwidth())
        self.assertGreaterEqual(browser._canvas.winfo_width(), browser._body.winfo_reqwidth())

    def test_the_filters_and_the_refresh_button_are_fully_inside_the_window(self):
        browser = self.open()
        self.app.update()

        for widget in (browser.status_box, browser.refresh_button):
            with self.subTest(widget=str(widget)):
                right_edge = widget.winfo_rootx() + widget.winfo_width() - browser.winfo_rootx()
                self.assertLessEqual(right_edge, browser.winfo_width())

    def test_refresh_fetches_again_and_keeps_the_filters(self):
        fetch = MagicMock(return_value=PLAYERS)
        browser = self.open(fetch)
        self.choose(browser.group_box, "Obchod")

        fetch.return_value = PLAYERS + [player("Prerov 3", True, "Obchod", "Prerov")]
        browser.refresh()
        self.wait_for(lambda: not browser._loading)

        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(browser.visible_names(), ["Prerov 1", "Prerov 2", "Prerov 3"])
        self.assertEqual(browser.group_box.get(), "Obchod")

    def test_a_filter_choice_that_no_longer_exists_falls_back_to_all(self):
        fetch = MagicMock(return_value=PLAYERS)
        browser = self.open(fetch)
        self.choose(browser.group_box, "Kancelar")

        fetch.return_value = [p for p in PLAYERS if p["name"] != "Lobby"]
        browser.refresh()
        self.wait_for(lambda: not browser._loading)

        self.assertEqual(browser.group_box.get(), "(vše)")
        self.assertEqual(len(browser.visible_names()), 3)

    def test_the_window_stays_responsive_while_loading(self):
        started = time.monotonic()
        browser = PlayerBrowser(self.app, url="u", login="l", password="p", account_name="A",
                                fetch=lambda *_: (time.sleep(0.4), PLAYERS)[1])
        self.addCleanup(browser.destroy)

        self.assertLess(time.monotonic() - started, 0.3)  # the constructor did not wait for the server
        self.assertEqual(browser.status_var.get(), "Načítám playery...")
        self.assertTrue(browser.refresh_button.instate(["disabled"]))
        self.wait_for(lambda: not browser._loading)
        self.assertTrue(browser.refresh_button.instate(["!disabled"]))


class LayoutTest(BrowserTestCase):
    def test_the_filters_stand_in_the_order_of_the_columns(self):
        browser = self.open()
        self.app.update()

        order = [browser.name_entry, browser.status_box, browser.group_box, browser.location_box, browser.label_box]
        positions = [widget.winfo_rootx() for widget in order]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(len(set(positions)), 5)
        self.assertEqual([key for key, _, _ in COLUMNS[:4]], ["name", "status", "group", "location"])

    def test_the_buttons_have_a_row_of_their_own_above_the_filters(self):
        browser = self.open()
        self.app.update()

        buttons = [browser.refresh_button, browser.reset_button, browser.default_columns_button]
        self.assertEqual([b.cget("text") for b in buttons], ["Aktualizovat", "Reset", "Výchozí sloupce"])
        self.assertEqual(len({b.winfo_rooty() for b in buttons}), 1)  # one row
        self.assertEqual([b.winfo_rootx() for b in buttons], sorted(b.winfo_rootx() for b in buttons))
        filter_widgets = (browser.name_entry, browser.status_box, browser.group_box, browser.location_box,
                          browser.label_box)
        for button in buttons:
            for widget in filter_widgets:
                self.assertLess(button.winfo_rooty() + button.winfo_height(), widget.winfo_rooty())

    def test_the_buttons_have_tooltips(self):
        browser = self.open()

        texts = [b.tooltip._text() for b in (browser.refresh_button, browser.reset_button,
                                             browser.default_columns_button)]
        self.assertEqual(len(set(texts)), 3)
        self.assertTrue(all(texts))

    def test_black_lines_separate_the_columns_in_the_header_and_beside_the_rows(self):
        browser = self.open()
        self.app.update()

        self.assertEqual(len(browser._header_separators), len(COLUMNS))
        self.assertEqual(len(browser._body_separators), len(COLUMNS))
        rows_height = max(w.winfo_y() + w.winfo_height() for w in browser._widgets[id(browser._visible[-1])])
        for line in browser._body_separators:
            self.assertEqual(str(line.cget("background")), SEPARATOR_COLOR)
            self.assertEqual(line.winfo_width(), 1)
            self.assertGreaterEqual(line.winfo_height(), rows_height - 2)
        for header, body in zip(browser._header_separators, browser._body_separators):
            self.assertAlmostEqual(header.winfo_x() + header.winfo_width() // 2, body.winfo_x(), delta=1)

    def test_a_long_text_is_cut_off_and_does_not_push_the_columns_apart(self):
        players = [player("N" * 300, True, "G" * 300, "L" * 300)] + PLAYERS
        browser = self.open(players=players)
        self.app.update()

        first = browser._widgets[id(browser._visible[0])]
        for index, (key, _, _) in enumerate(COLUMNS):
            with self.subTest(column=key):
                self.assertEqual(browser._header_cells[key].winfo_x(), first[index].winfo_x())
                self.assertEqual(first[index].winfo_width(), browser._header_cells[key].winfo_width())


class ColumnWidthTest(BrowserTestCase):
    def drag(self, browser, key, distance):
        separator = browser._header_separators[[k for k, _, _ in COLUMNS].index(key)]
        x = separator.winfo_rootx() + 3
        separator.event_generate("<ButtonPress-1>", x=3, y=5, rootx=x, rooty=100)
        separator.event_generate("<B1-Motion>", x=3, y=5, rootx=x + distance // 2, rooty=100, state=0x100)
        separator.event_generate("<B1-Motion>", x=3, y=5, rootx=x + distance, rooty=100, state=0x100)
        separator.event_generate("<ButtonRelease-1>", x=3, y=5, rootx=x + distance, rooty=100)
        self.app.update()

    def test_dragging_a_line_widens_the_column_on_its_left_and_moves_the_others(self):
        browser = self.open()
        self.app.update()
        before = browser.column_widths()
        next_x = browser._header_cells["status"].winfo_x()

        self.drag(browser, "name", 60)

        self.assertEqual(browser.column_widths()["name"], before["name"] + 60)
        self.assertEqual(browser.column_widths()["status"], before["status"])
        self.assertEqual(browser._header_cells["status"].winfo_x(), next_x + 60)
        first = browser._widgets[id(browser._visible[0])]
        self.assertEqual(first[1].winfo_x(), next_x + 60)  # the rows moved with the header

    def test_dragging_left_narrows_and_stops_at_the_minimum(self):
        browser = self.open()
        before = browser.column_widths()["group"]

        self.drag(browser, "group", -30)
        self.assertEqual(browser.column_widths()["group"], before - 30)
        self.drag(browser, "group", -5000)
        self.assertEqual(browser.column_widths()["group"], MIN_COLUMN_WIDTH)

    def test_the_width_has_an_upper_limit_too(self):
        browser = self.open()

        self.drag(browser, "name", 10 ** 6)

        self.assertEqual(browser.column_widths()["name"], MAX_COLUMN_WIDTH)

    def test_the_widths_are_saved_when_the_button_is_released_not_during_the_drag(self):
        saved = []
        browser = self.open(save_column_widths=saved.append)
        separator = browser._header_separators[0]
        x = separator.winfo_rootx() + 3

        separator.event_generate("<ButtonPress-1>", x=3, y=5, rootx=x, rooty=100)
        separator.event_generate("<B1-Motion>", x=3, y=5, rootx=x + 20, rooty=100, state=0x100)
        self.assertEqual(saved, [])
        separator.event_generate("<ButtonRelease-1>", x=3, y=5, rootx=x + 20, rooty=100)

        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0], browser.column_widths())

    def test_a_click_on_a_line_without_moving_changes_nothing(self):
        browser = self.open()
        before = browser.column_widths()

        self.drag(browser, "name", 0)

        self.assertEqual(browser.column_widths(), before)

    def test_saved_widths_are_used_when_the_window_opens(self):
        browser = self.open(column_widths={"name": 333, "location": 111})
        self.app.update()

        widths = browser.column_widths()
        self.assertEqual((widths["name"], widths["location"]), (333, 111))
        self.assertEqual(browser._header_cells["name"].winfo_width() + 2 * 4, 333)
        default = self.open().column_widths()
        self.assertEqual(widths["group"], default["group"])

    def test_nonsense_in_the_saved_widths_is_ignored(self):
        for raw in (None, "text", [1, 2], {"name": "wide"}, {"name": -5}, {"name": 5}, {"name": 10 ** 9},
                    {"name": True}, {"name": 12.5}, {"unknown": 200}):
            with self.subTest(raw=raw):
                self.assertEqual(valid_widths(raw), {})
        self.assertEqual(valid_widths({"name": 200, "group": "x", "status": 90}), {"name": 200, "status": 90})

    def test_default_columns_restores_the_original_widths_and_forgets_the_saved_ones(self):
        saved = []
        default = self.open().column_widths()
        browser = self.open(column_widths={"name": 333}, save_column_widths=saved.append)

        browser.default_columns_button.invoke()

        self.assertEqual(browser.column_widths(), default)
        self.assertEqual(saved, [{}])
        self.app.update()
        self.assertEqual(browser._header_cells["name"].winfo_width() + 8, default["name"])

    def test_a_table_wider_than_the_window_scrolls_sideways_with_its_header(self):
        browser = self.open(column_widths={"name": 1400, "group": 1400})
        self.app.update()

        self.assertTrue(browser._x_scrollbar.winfo_ismapped())
        browser._scroll_x("moveto", 0.5)
        self.app.update()
        self.assertGreater(browser._canvas.xview()[0], 0)
        self.assertEqual(browser._header_canvas.xview()[0], browser._canvas.xview()[0])
        header_x = browser._header_cells["status"].winfo_rootx()
        row_x = browser._widgets[id(browser._visible[0])][1].winfo_rootx()
        self.assertEqual(header_x, row_x)  # still lined up after scrolling

    def test_the_horizontal_scroll_bar_is_hidden_while_everything_fits(self):
        browser = self.open()
        self.app.update()

        self.assertFalse(browser._x_scrollbar.winfo_ismapped())

    def test_the_window_never_opens_wider_than_the_screen(self):
        browser = self.open(column_widths={"name": 1500, "group": 1500, "location": 1500})
        self.app.update()

        self.assertLessEqual(browser.winfo_width(), self.app.winfo_screenwidth())


class ResizeZoneTest(BrowserTestCase):
    """The whole length of a line, EDGE_ZONE pixels to each side of it, is where the column can be grabbed."""

    def setUp(self):
        super().setUp()
        self.browser = self.open()
        self.app.update()
        self.line = self.browser._header_separators[0].winfo_rootx() + 3  # the x of the first line
        self.body_cell = self.browser._widgets[id(self.browser._visible[0])][0]
        self.header_cell = self.browser._header_cells["status"]

    def event(self, widget, kind, offset, **options):
        widget.event_generate(kind, x=2, y=2, rootx=self.line + offset, rooty=widget.winfo_rooty() + 2, **options)

    def drag_on(self, widget, start, distance):
        self.event(widget, "<ButtonPress-1>", start)
        self.event(widget, "<B1-Motion>", start + distance // 2, state=0x100)
        self.event(widget, "<B1-Motion>", start + distance, state=0x100)
        self.event(widget, "<ButtonRelease-1>", start + distance)
        self.app.update()

    def test_the_zone_is_ten_pixels_to_each_side_of_the_line(self):
        self.assertEqual(EDGE_ZONE, 10)
        for offset in (-10, -5, 0, 5, 10):
            with self.subTest(offset=offset):
                self.assertEqual(self.browser._edge_at(self.line + offset), "name")
        for offset in (-11, 11, -40, 40):
            with self.subTest(offset=offset):
                self.assertIsNone(self.browser._edge_at(self.line + offset))

    def test_the_pointer_changes_over_the_zone_in_the_rows_and_in_the_header(self):
        for widget, own_cursor in ((self.body_cell, ""), (self.header_cell, SORT_CURSOR)):
            for offset in (-10, 0, 10):
                with self.subTest(widget=str(widget), offset=offset):
                    self.event(widget, "<Motion>", offset)
                    self.assertEqual(str(widget.cget("cursor")), RESIZE_CURSOR)
            for offset in (-11, 11):
                with self.subTest(widget=str(widget), offset=offset):
                    self.event(widget, "<Motion>", offset)
                    self.assertEqual(str(widget.cget("cursor")), own_cursor)

    def test_the_pointer_goes_back_when_it_leaves(self):
        self.event(self.body_cell, "<Motion>", 3)
        self.assertEqual(str(self.body_cell.cget("cursor")), RESIZE_CURSOR)

        self.body_cell.event_generate("<Leave>")

        self.assertEqual(str(self.body_cell.cget("cursor")), "")

    def test_the_rows_can_be_used_to_resize_not_only_the_header(self):
        before = self.browser.column_widths()["name"]

        self.drag_on(self.body_cell, 4, 50)

        self.assertEqual(self.browser.column_widths()["name"], before + 50)

    def test_pressing_and_holding_resizes_live_and_letting_go_saves(self):
        saved = []
        browser = self.open(save_column_widths=saved.append)
        self.app.update()
        line = browser._header_separators[1].winfo_rootx() + 3
        cell = browser._widgets[id(browser._visible[0])][2]
        before = browser.column_widths()["status"]

        def at(offset, kind, **options):
            cell.event_generate(kind, x=2, y=2, rootx=line + offset, rooty=cell.winfo_rooty() + 2, **options)
        at(0, "<ButtonPress-1>")
        at(15, "<B1-Motion>", state=0x100)
        self.assertEqual(browser.column_widths()["status"], before + 15)  # follows the pointer while held
        at(40, "<B1-Motion>", state=0x100)
        self.assertEqual(browser.column_widths()["status"], before + 40)
        at(-20, "<B1-Motion>", state=0x100)
        self.assertEqual(browser.column_widths()["status"], before - 20)  # and back again
        self.assertEqual(saved, [])
        at(-20, "<ButtonRelease-1>")

        self.assertEqual(saved, [browser.column_widths()])
        at(60, "<B1-Motion>", state=0x100)  # moving without the button changes nothing any more
        self.assertEqual(browser.column_widths()["status"], before - 20)

    def test_the_resize_pointer_stays_during_the_drag_wherever_the_pointer_is(self):
        self.event(self.body_cell, "<ButtonPress-1>", 0)

        self.event(self.body_cell, "<Motion>", 200)

        self.assertEqual(str(self.body_cell.cget("cursor")), RESIZE_CURSOR)
        self.event(self.body_cell, "<ButtonRelease-1>", 200)

    def test_a_press_outside_the_zone_does_not_resize(self):
        before = self.browser.column_widths()

        self.drag_on(self.body_cell, 11, 50)

        self.assertEqual(self.browser.column_widths(), before)

    def test_a_click_on_a_header_sorts_but_not_inside_a_zone(self):
        self.assertEqual(self.browser._sort, ("name", False))
        self.event(self.header_cell, "<ButtonPress-1>", 4)  # the status header, in the zone of the name column's line
        self.event(self.header_cell, "<ButtonRelease-1>", 4)
        self.assertEqual(self.browser._sort, ("name", False))

        self.header_cell.event_generate("<ButtonPress-1>", x=2, y=2, rootx=self.line + 60, rooty=10)
        self.header_cell.event_generate("<ButtonRelease-1>", x=2, y=2, rootx=self.line + 60, rooty=10)

        self.assertEqual(self.browser._sort, ("status", False))

    def test_widgets_outside_the_table_are_left_alone(self):
        entry = self.browser.name_entry
        before = str(entry.cget("cursor"))

        self.event(entry, "<Motion>", 0)
        self.event(entry, "<ButtonPress-1>", 0)

        self.assertEqual(str(entry.cget("cursor")), before)
        self.assertIsNone(self.browser._drag)

    def test_the_zones_follow_the_lines_when_a_column_is_widened_and_when_the_table_is_scrolled(self):
        self.drag_on(self.body_cell, 0, 80)
        moved = self.browser._header_separators[1].winfo_rootx() + 3
        self.assertEqual(self.browser._edge_at(moved), "status")

        browser = self.open(column_widths={"name": 1400, "group": 1400})
        self.app.update()
        browser._scroll_x("moveto", 0.5)
        self.app.update()
        scrolled = browser._header_separators[2].winfo_rootx() + 3
        self.assertEqual(browser._edge_at(scrolled), "group")
        self.assertIsNone(browser._edge_at(scrolled + 40))


class ResetFiltersTest(BrowserTestCase):
    def test_reset_clears_every_filter_and_shows_all_the_players_again(self):
        browser = self.open()
        browser.name_var.set("lob")
        self.choose(browser.status_box, "Online")
        self.choose(browser.group_box, "Kancelar")
        self.choose(browser.location_box, "Praha")
        self.choose(browser.label_box, "vstup")
        self.wait_for(lambda: browser.visible_names() == ["Lobby"])

        browser.reset_button.invoke()

        self.assertEqual(browser.name_var.get(), "")
        for box in (browser.status_box, browser.group_box, browser.location_box, browser.label_box):
            self.assertEqual(box.get(), "(vše)")
        self.assertEqual(len(browser.visible_names()), 4)
        self.assertEqual(browser.status_var.get(), "Zobrazeno 4 z 4")

    def test_reset_keeps_the_sort_order_and_does_not_ask_the_server_again(self):
        fetch = MagicMock(return_value=PLAYERS)
        browser = self.open(fetch)
        browser._header_cells["name"].event_generate("<Button-1>")  # descending

        browser.name_var.set("prerov")
        browser.reset_button.invoke()

        self.assertEqual(browser.visible_names(), ["Sklad", "Prerov 2", "Prerov 1", "Lobby"])
        self.assertEqual(fetch.call_count, 1)

    def test_the_pending_name_filter_does_not_undo_the_reset(self):
        browser = self.open()
        browser.name_var.set("sklad")  # its delayed filtering is still pending
        browser.reset_button.invoke()

        for _ in range(30):
            self.app.update()
            time.sleep(0.01)

        self.assertEqual(len(browser.visible_names()), 4)


class PlayerBrowserErrorTest(BrowserTestCase):
    def failing(self, error):
        def fetch(*_):
            raise error
        return self.open(fetch)

    def test_the_failures_are_explained_and_no_table_is_shown(self):
        cases = ((LoginError(), "Přihlašovací údaje nejsou platné."),
                 (requests.exceptions.ConnectionError(), "Chyba internetového připojení."),
                 (requests.exceptions.Timeout(), "Chyba internetového připojení."),
                 (RuntimeError("boom secret-token"), "Server nevrátil odpověď."))
        for error, expected in cases:
            with self.subTest(error=type(error).__name__):
                browser = self.failing(error)

                self.assertIn(expected, browser.status_var.get())
                self.assertTrue(browser.status_var.get().startswith("Playery se nepodařilo načíst"))
                self.assertNotIn("secret-token", browser.status_var.get())
                self.assertEqual(browser.visible_names(), [])
                self.assertTrue(browser.refresh_button.instate(["!disabled"]))

    def test_an_http_error_shows_its_code(self):
        response = MagicMock(status_code=503)

        browser = self.failing(requests.exceptions.HTTPError(response=response))

        self.assertIn("503", browser.status_var.get())

    def test_refresh_after_a_failure_can_succeed(self):
        answers = [requests.exceptions.ConnectionError(), PLAYERS]

        def fetch(*_):
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        browser = self.open(fetch)
        browser.refresh()
        self.wait_for(lambda: not browser._loading)

        self.assertEqual(len(browser.visible_names()), 4)

    def test_closing_the_window_while_loading_does_not_raise(self):
        browser = PlayerBrowser(self.app, url="u", login="l", password="p", account_name="A",
                                fetch=lambda *_: (time.sleep(0.2), PLAYERS)[1])
        browser.destroy()
        for _ in range(40):
            self.app.update()
            time.sleep(0.01)


class ServerPlayersTest(unittest.TestCase):
    def test_all_pages_are_fetched(self):
        server = ServerApi.__new__(ServerApi)
        pages = {None: {"data": {"objects": [{"name": "a"}], "pages": 3}},
                 2: {"data": {"objects": [{"name": "b"}], "pages": 3}},
                 3: {"data": {"objects": [{"name": "c"}], "pages": 3}}}
        server._make_request = MagicMock(side_effect=lambda method, endpoint, params=None: pages[(params or {}).get("page")])

        self.assertEqual([p["name"] for p in server.get_player_objects()], ["a", "b", "c"])

    def test_a_single_page_needs_one_request(self):
        server = ServerApi.__new__(ServerApi)
        server._make_request = MagicMock(return_value={"data": {"objects": [{"name": "a"}]}})

        self.assertEqual(server.get_player_objects(), [{"name": "a"}])
        server._make_request.assert_called_once()


class MainWindowTest(BrowserTestCase):
    def choose_action(self):
        self.app.entity_type_var.set("Players")
        self.app.update_action_selection()
        label = next(label for label, key in self.app.entity_actions["Players"].items() if key == ACTION)
        self.app.option_choose_action.set(label)
        self.app.reset_data()
        self.app.update()
        return label

    def test_the_action_is_in_the_players_menu_and_needs_no_input(self):
        label = self.choose_action()

        self.assertEqual(label, "Snímek obrazovky - zobrazit")
        self.assertEqual(self.app.current_action(), ACTION)
        self.assertNotEqual(self.app.input_prompt_button.winfo_manager(), "grid")  # the input button is hidden

    def test_running_it_without_login_shows_a_hint_and_no_window(self):
        with patch.object(gui.messagebox, "showinfo") as info:
            self.app.perform_show_action(ACTION, "https://x", "", "", None)

        info.assert_called_once()
        self.assertIsNone(self.app._player_browser)

    def test_running_it_opens_one_window_and_running_again_reuses_it(self):
        with patch("gui_app.gui.PlayerBrowser") as browser_class:
            first = browser_class.return_value
            first.winfo_exists.return_value = True
            first.connection = ("https://x", "jane")
            self.app.perform_show_action(ACTION, "https://x", "jane", "pw", None)
            self.app.perform_show_action(ACTION, "https://x", "jane", "pw", None)

            browser_class.assert_called_once()
            first.lift.assert_called_once()

    def test_another_login_replaces_the_window(self):
        with patch("gui_app.gui.PlayerBrowser") as browser_class:
            first = browser_class.return_value
            first.winfo_exists.return_value = True
            first.connection = ("https://x", "jane")
            self.app.perform_show_action(ACTION, "https://x", "jane", "pw", None)
            self.app.perform_show_action(ACTION, "https://y", "john", "pw", None)

            first.destroy.assert_called_once()
            self.assertEqual(browser_class.call_count, 2)

    def test_execute_action_dispatches_show_actions(self):
        self.app.account_data["Demo"] = {"url": "https://x", "names": {"jane": {"login": "jane"}}}
        self.app.option_choose_administration.set("Demo")
        self.app.option_choose_name.set("jane")
        self.app.input_for_password.insert(0, "pw")
        self.choose_action()
        with patch.object(self.app, "open_player_browser") as opened:
            self.app.execute_action()

        opened.assert_called_once_with("https://x", "jane", "pw")

    def test_the_window_gets_the_widths_saved_for_the_account_and_saves_the_new_ones_there(self):
        self.app.all_data["logins"]["Demo"] = {"url": "https://x", "names": {"jane": {"login": "jane"}},
                                               "player_columns": {"name": 333}}
        self.app.account_data = self.app.all_data["logins"]
        self.app.all_data["logins"]["Other"] = {"url": "https://y", "names": {}}
        self.app.save_account_configs()
        self.app.option_choose_administration.set("Demo")
        with patch("gui_app.gui.PlayerBrowser") as browser_class:
            self.app.open_player_browser("https://x", "jane", "pw")
            options = browser_class.call_args.kwargs

            self.assertEqual(options["column_widths"], {"name": 333})
            options["save_column_widths"]({"name": 400, "group": 90})

        with open(self.app.config_file, encoding="utf-8") as file:
            saved = json.load(file)["logins"]
        self.assertEqual(saved["Demo"]["player_columns"], {"name": 400, "group": 90})
        self.assertNotIn("player_columns", saved["Other"])
        with patch("gui_app.gui.PlayerBrowser") as browser_class:
            self.app._player_browser = None
            self.app.open_player_browser("https://x", "jane", "pw")
            self.assertEqual(browser_class.call_args.kwargs["column_widths"], {"name": 400, "group": 90})
            browser_class.call_args.kwargs["save_column_widths"]({})
        with open(self.app.config_file, encoding="utf-8") as file:
            self.assertNotIn("player_columns", json.load(file)["logins"]["Demo"])

    def test_saving_widths_for_a_removed_account_writes_nothing(self):
        self.app.save_player_columns("Gone", {"name": 300})

        with open(self.app.config_file, encoding="utf-8") as file:
            self.assertEqual(json.load(file)["logins"], {})

    def test_the_window_closes_when_the_language_changes(self):
        browser = self.open()
        self.app._player_browser = browser

        self.app.refresh_ui()

        self.assertFalse(browser.winfo_exists())
        self.assertIsNone(self.app._player_browser)


class MessageKeysTest(unittest.TestCase):
    """Every literal message key the code asks for must exist in both languages (a missing one is a KeyError)."""

    def test_no_key_used_in_the_code_is_missing(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        used = {}
        for directory in ("gui_app", "processor", "util", "api_testing"):
            for path in glob.glob(os.path.join(root, directory, "*.py")):
                with open(path, encoding="utf-8") as file:
                    for key in re.findall(r'get_message\(\s*"([A-Za-z0-9_.]+)"', file.read()):
                        used.setdefault(key, path)
        for language in ("cz", "en"):
            lang = LanguageManager(language)
            for key, path in sorted(used.items()):
                with self.subTest(language=language, key=key):
                    node = lang.messages[language]
                    for part in key.split("."):
                        self.assertIn(part, node, f"{key} (used in {os.path.basename(path)}) is missing")
                        node = node[part]


if __name__ == "__main__":
    unittest.main()
