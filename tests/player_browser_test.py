import json
import os
import re
import glob
import tempfile
import threading
import time
import tkinter as tk
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import requests

from api_testing.request_calls import LoginError, ResponseError, ServerApi
from gui_app import gui
from gui_app.color_button import GREEN, RED, ColorButton
from gui_app.player_browser import (COLUMNS, EDGE_ZONE, MAX_COLUMN_WIDTH, MIN_COLUMN_WIDTH, RESIZE_CURSOR,
                                    SEPARATOR_COLOR, SEPARATOR_WIDTH, SNAPSHOT_COLUMN_MINSIZE, SORT_CURSOR, TOGGLE_COLUMNS,
                                    PlayerBrowser, valid_hidden, valid_widths)
from util.language import LanguageManager

ACTION = "show_player_snapshots"


def player(name, connected=True, group="Obchod", location="Praha", labels=(), uploaded=0, reported=0, notes=""):
    return {"name": name, "isConnected": connected, "group": {"name": group} if group else None,
            "configLocation": location, "labels": list(labels), "lastUpload": uploaded, "lastReported": reported,
            "notes": notes}


def ago(**delta):
    return int((datetime.now() - timedelta(**delta)).timestamp() * 1000)


def make_players():
    return [
        player("Lobby", True, "Kancelar", "Praha", ["vstup"], uploaded=ago(seconds=30), reported=ago(seconds=20),
               notes="hlavní vchod"),
        player("Prerov 1", False, "Obchod", "Prerov", ["vstup", "test"], uploaded=ago(days=40),
               reported=ago(days=2), notes="rozbitá\nobrazovka"),
        player("Prerov 2", True, "Obchod", "Prerov", reported=ago(minutes=3)),
        player("Sklad", True, None, "", notes="rezerva"),
    ]


PLAYERS = make_players()  # refreshed for every test: the times in it are relative to now


class BrowserTestCase(unittest.TestCase):
    def setUp(self):
        PLAYERS[:] = make_players()  # in place: the tests hold on to this list
        self.clock = [1000.0]  # the time of the refresh interval: the tests move it, they do not wait
        clock_patch = patch("gui_app.player_browser._clock", lambda: self.clock[0])
        clock_patch.start()
        self.addCleanup(clock_patch.stop)
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

    def advance(self, browser, seconds):
        """Lets time pass for the refresh interval."""
        self.clock[0] += seconds
        browser._update_refresh_state()

    def tick(self, browser, box, *values, on=True):
        """Ticks (or unticks) values in the list of a multi-choice filter and waits for the table to follow."""
        for value in values:
            box._vars[value].set(on)
        self.wait_for(lambda: browser._filter_after_id is None)

    def type_into(self, browser, variable, text):
        variable.set(text)
        self.wait_for(lambda: browser._filter_after_id is None)


class PlayerBrowserTest(BrowserTestCase):
    def test_all_players_are_listed_sorted_by_name_with_a_count(self):
        browser = self.open()

        self.assertEqual(browser.visible_names(), ["Lobby", "Prerov 1", "Prerov 2", "Sklad"])
        self.assertEqual(browser.status_var.get(), "Zobrazeno 4 z 4")
        self.assertEqual(browser.title(), "Snímek obrazovky - Demo")

    def test_the_row_shows_state_group_location_and_when_it_was_synced(self):
        browser = self.open()
        cells = {row.name: [w for w in browser._widgets[id(row)][1:]] for row in browser._rows}  # without the button

        lobby, offline, ungrouped = cells["Lobby"], cells["Prerov 1"], cells["Sklad"]
        self.assertEqual([c.cget("text") for c in lobby[:5]], ["Lobby", "Online", "Kancelar", "Praha", "vstup"])
        self.assertEqual(offline[1].cget("text"), "Offline")
        self.assertNotEqual(str(lobby[1].cget("foreground")), str(offline[1].cget("foreground")))
        self.assertEqual(offline[4].cget("text"), "vstup, test")  # the categories, comma separated
        self.assertRegex(lobby[5].cget("text"), r"^\d\d\.\d\d\.\d{4} \d\d:\d\d$")  # synced
        self.assertRegex(lobby[6].cget("text"), r"^\d\d\.\d\d\.\d{4} \d\d:\d\d$")  # reported
        self.assertEqual(lobby[7].cget("text"), "hlavní vchod")
        self.assertEqual(offline[7].cget("text"), "rozbitá obrazovka")  # a note is one line
        self.assertEqual(ungrouped[2].cget("text"), "")
        self.assertEqual((ungrouped[5].cget("text"), ungrouped[6].cget("text")), ("nikdy", "nikdy"))

    def test_every_row_has_a_snapshot_button_that_is_inactive_for_now(self):
        browser = self.open()

        buttons = [widgets[0] for widgets in browser._widgets.values()]
        self.assertEqual(len(buttons), 4)
        for button in buttons:
            self.assertEqual(button.cget("text"), "Snímek")
            self.assertTrue(button.instate(["disabled"]))

    def test_the_name_filter_takes_a_part_of_the_name(self):
        browser = self.open()

        browser.name_var.set("rerov")
        self.wait_for(lambda: browser.visible_names() == ["Prerov 1", "Prerov 2"])
        self.assertEqual(browser.status_var.get(), "Zobrazeno 2 z 4")

    def test_state_group_location_and_category_filters(self):
        browser = self.open()

        self.tick(browser, browser.group_box, "Obchod")
        self.assertEqual(browser.visible_names(), ["Prerov 1", "Prerov 2"])
        self.choose(browser.status_box, "Online")
        self.assertEqual(browser.visible_names(), ["Prerov 2"])
        self.choose(browser.status_box, "(vše)")
        self.tick(browser, browser.label_box, "test")
        self.assertEqual(browser.visible_names(), ["Prerov 1"])
        self.tick(browser, browser.label_box, "test", on=False)
        self.tick(browser, browser.group_box, "Obchod", on=False)
        self.tick(browser, browser.location_box, "Praha")
        self.assertEqual(browser.visible_names(), ["Lobby"])

    def test_several_ticked_values_are_alternatives(self):
        browser = self.open()

        self.tick(browser, browser.group_box, "Kancelar", "Obchod")
        self.assertEqual(len(browser.visible_names()), 3)
        self.tick(browser, browser.location_box, "Praha", "Prerov")
        self.assertEqual(browser.visible_names(), ["Lobby", "Prerov 1", "Prerov 2"])
        self.tick(browser, browser.label_box, "vstup", "test")
        self.assertEqual(browser.visible_names(), ["Lobby", "Prerov 1"])

    def test_the_typed_text_and_the_ticks_apply_together(self):
        browser = self.open()

        self.type_into(browser, browser.group_box.text_var, "obch")
        self.assertEqual(browser.visible_names(), ["Prerov 1", "Prerov 2"])
        self.tick(browser, browser.group_box, "Kancelar")  # ticked, but the text does not match it
        self.assertEqual(browser.visible_names(), [])
        self.tick(browser, browser.group_box, "Obchod")
        self.assertEqual(browser.visible_names(), ["Prerov 1", "Prerov 2"])

    def test_the_text_of_the_category_field_and_the_other_text_filters(self):
        browser = self.open()

        self.type_into(browser, browser.label_box.text_var, "TES")
        self.assertEqual(browser.visible_names(), ["Prerov 1"])
        self.type_into(browser, browser.label_box.text_var, "")
        self.type_into(browser, browser.location_box.text_var, "praha")
        self.assertEqual(browser.visible_names(), ["Lobby"])
        self.type_into(browser, browser.location_box.text_var, "")
        self.type_into(browser, browser.note_var, "VCHOD")
        self.assertEqual(browser.visible_names(), ["Lobby"])
        self.type_into(browser, browser.note_var, "obrazovka")
        self.assertEqual(browser.visible_names(), ["Prerov 1"])

    def test_the_age_filters_of_synced_and_reported(self):
        browser = self.open()

        self.choose(browser.reported_box, "< 1 minuta")
        self.assertEqual(browser.visible_names(), ["Lobby"])
        self.choose(browser.reported_box, "> 1 den")
        self.assertEqual(browser.visible_names(), ["Prerov 1", "Sklad"])  # and the one that never reported
        self.choose(browser.reported_box, "(vše)")
        self.choose(browser.synced_box, "> 1 měsíc")
        self.assertEqual(browser.visible_names(), ["Prerov 1", "Prerov 2", "Sklad"])  # and those never synced
        self.choose(browser.synced_box, "< 1 minuta")
        self.assertEqual(browser.visible_names(), ["Lobby"])
        self.choose(browser.reported_box, "> 1 den")  # both together: synced just now, but not reported for a day
        self.assertEqual(browser.visible_names(), [])

    def test_the_age_filters_offer_the_asked_for_choices(self):
        browser = self.open()

        expected = ["(vše)", "< 1 minuta", "> 1 minuta", "> 5 minut", "> 60 minut", "> 3 hodiny", "> 6 hodin",
                    "> 12 hodin", "> 1 den", "> 1 týden", "> 1 měsíc"]
        self.assertEqual(list(browser.synced_box["values"]), expected)
        self.assertEqual(list(browser.reported_box["values"]), expected)

    def test_the_choices_offer_what_the_account_has(self):
        browser = self.open()

        self.assertEqual([label for label, _ in browser.group_box._choices],
                         ["(bez skupiny)", "Kancelar", "Obchod"])
        self.assertEqual([label for label, _ in browser.label_box._choices], ["test", "vstup"])
        self.assertEqual([label for label, _ in browser.location_box._choices], ["Praha", "Prerov"])
        self.assertEqual(list(browser.status_box["values"]), ["(vše)", "Online", "Offline"])

    def test_the_players_without_a_group_have_their_own_choice(self):
        browser = self.open()

        self.tick(browser, browser.group_box, "")

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
                self.assertEqual(browser._header_cells[key].winfo_x(), first_row[index + 1].winfo_x())

    def test_the_window_is_wide_enough_for_the_table(self):
        browser = self.open()
        self.app.update()

        self.assertGreaterEqual(browser.winfo_width(), browser._header.winfo_reqwidth())
        self.assertGreaterEqual(browser._canvas.winfo_width(), browser._body.winfo_reqwidth())

    def test_the_filters_and_the_refresh_button_are_fully_inside_the_window(self):
        browser = self.open()
        self.app.update()

        for widget in (browser.note_entry, browser.refresh_button):
            with self.subTest(widget=str(widget)):
                right_edge = widget.winfo_rootx() + widget.winfo_width() - browser.winfo_rootx()
                self.assertLessEqual(right_edge, browser.winfo_width())

    def test_refresh_fetches_again_and_keeps_the_filters(self):
        fetch = MagicMock(return_value=PLAYERS)
        browser = self.open(fetch)
        self.tick(browser, browser.group_box, "Obchod")

        fetch.return_value = PLAYERS + [player("Prerov 3", True, "Obchod", "Prerov")]
        self.advance(browser, 11)
        browser.refresh()
        self.wait_for(lambda: not browser._loading)

        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(browser.visible_names(), ["Prerov 1", "Prerov 2", "Prerov 3"])
        self.assertEqual(browser.group_box.checked(), frozenset({"Obchod"}))

    def test_a_ticked_value_that_no_longer_exists_is_dropped(self):
        fetch = MagicMock(return_value=PLAYERS)
        browser = self.open(fetch)
        self.tick(browser, browser.group_box, "Kancelar")

        fetch.return_value = [p for p in PLAYERS if p["name"] != "Lobby"]
        self.advance(browser, 11)
        browser.refresh()
        self.wait_for(lambda: not browser._loading)

        self.assertEqual(browser.group_box.checked(), frozenset())
        self.assertEqual(len(browser.visible_names()), 3)

    def test_the_window_stays_responsive_while_loading(self):
        started = time.monotonic()
        browser = PlayerBrowser(self.app, url="u", login="l", password="p", account_name="A",
                                fetch=lambda *_: (time.sleep(0.4), PLAYERS)[1])
        self.addCleanup(browser.destroy)

        self.assertLess(time.monotonic() - started, 0.3)  # the constructor did not wait for the server
        self.assertEqual(browser.status_var.get(), "Načítám playery...")
        self.assertTrue(browser.refresh_button.instate(["!disabled"]))  # a press is remembered, so it is always on
        self.wait_for(lambda: not browser._loading)


class LayoutTest(BrowserTestCase):
    def all_filters(self, browser):
        return [browser.name_entry, browser.status_box, browser.group_box, browser.location_box, browser.label_box,
                browser.synced_box, browser.reported_box, browser.note_entry]

    def test_every_filter_starts_at_the_left_edge_of_its_column_and_is_as_wide_as_it(self):
        browser = self.open()
        self.app.update()

        for key, widget in zip((k for k, _, _ in COLUMNS), self.all_filters(browser)):
            header = browser._header_cells[key]
            with self.subTest(column=key):
                self.assertEqual(widget.winfo_rootx(), header.winfo_rootx())
                self.assertEqual(widget.winfo_width(), header.winfo_width())

    def test_the_filters_are_a_row_between_the_buttons_and_the_header_and_the_button_column_has_none(self):
        browser = self.open()
        self.app.update()

        header_top = browser._header_cells["name"].winfo_rooty()
        for widget in self.all_filters(browser):
            self.assertLess(widget.winfo_rooty() + widget.winfo_height(), header_top)
            self.assertGreater(widget.winfo_rooty(), browser.refresh_button.winfo_rooty()
                               + browser.refresh_button.winfo_height())
            self.assertGreater(widget.winfo_rootx(), browser._widgets[id(browser._visible[0])][0].winfo_rootx()
                               + browser._widgets[id(browser._visible[0])][0].winfo_width() - 1)
        heights = {widget.winfo_rooty() for widget in self.all_filters(browser)}
        self.assertLess(max(heights) - min(heights), 6)  # one row (the field types differ a little in height)

    def test_the_filters_have_no_labels_the_header_below_names_them(self):
        browser = self.open()

        labels = [w for w in browser._filters.winfo_children() if isinstance(w, tk.Label)]
        self.assertEqual(labels, [])

    def test_the_filters_stay_above_their_columns_when_a_column_is_widened_or_narrowed(self):
        browser = self.open()
        self.app.update()
        separator = browser._header_separators[2]  # the line after the group column
        x = separator.winfo_rootx() + 3

        for distance in (60, -30):
            with self.subTest(distance=distance):
                separator.event_generate("<ButtonPress-1>", x=3, y=5, rootx=x, rooty=100)
                separator.event_generate("<B1-Motion>", x=3, y=5, rootx=x + distance, rooty=100, state=0x100)
                separator.event_generate("<ButtonRelease-1>", x=3, y=5, rootx=x + distance, rooty=100)
                self.app.update()
                for key, widget in zip((k for k, _, _ in COLUMNS), self.all_filters(browser)):
                    header = browser._header_cells[key]
                    self.assertEqual((widget.winfo_rootx(), widget.winfo_width()),
                                     (header.winfo_rootx(), header.winfo_width()))
                x = separator.winfo_rootx() + 3

    def test_a_narrow_column_makes_its_filter_narrower_not_wider_than_the_column(self):
        browser = self.open(column_widths={"group": 90})
        self.app.update()

        widget, header = browser.group_box, browser._header_cells["group"]
        self.assertEqual(widget.winfo_width(), header.winfo_width())
        self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), header.winfo_rootx() + header.winfo_width())
        wide = self.open(column_widths={"group": 400})
        self.app.update()
        self.assertLess(widget.winfo_width(), wide.group_box.winfo_width())

    def test_a_column_cannot_be_made_so_narrow_that_its_filter_disappears(self):
        browser = self.open()
        self.app.update()
        for index, (key, _, _) in enumerate(COLUMNS):
            separator = browser._header_separators[index]
            x = separator.winfo_rootx() + 3
            separator.event_generate("<ButtonPress-1>", x=3, y=5, rootx=x, rooty=100)
            separator.event_generate("<B1-Motion>", x=3, y=5, rootx=x - 3000, rooty=100, state=0x100)
            separator.event_generate("<ButtonRelease-1>", x=3, y=5, rootx=x - 3000, rooty=100)
            self.app.update()

        for key, widget in zip((k for k, _, _ in COLUMNS), self.all_filters(browser)):
            header = browser._header_cells[key]
            with self.subTest(column=key):
                self.assertEqual(browser.column_widths()[key], browser._min_widths[key])
                self.assertGreaterEqual(browser._min_widths[key], MIN_COLUMN_WIDTH)
                self.assertTrue(widget.winfo_ismapped())
                self.assertGreaterEqual(widget.winfo_width(), 30)
                self.assertEqual((widget.winfo_rootx(), widget.winfo_width()),
                                 (header.winfo_rootx(), header.winfo_width()))
                self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                                     header.winfo_rootx() + header.winfo_width())

    def test_saved_widths_below_the_minimum_are_raised_when_the_window_opens(self):
        browser = self.open(column_widths={"group": 60, "name": 60, "note": 60})
        self.app.update()

        for key in ("group", "name", "note"):
            self.assertGreaterEqual(browser.column_widths()[key], browser._min_widths[key])
            self.assertTrue(self._filter(browser, key).winfo_width() >= 30)

    @staticmethod
    def _filter(browser, key):
        return browser._filter_widgets[key]

    def test_the_multi_choice_filters_need_room_for_the_count_of_ticks(self):
        browser = self.open()
        self.assertGreater(browser._min_widths["group"], browser._min_widths["synced"])
        for key in ("group", "location", "label"):
            self.assertEqual(browser._min_widths[key], max(MIN_COLUMN_WIDTH, browser._filter_widgets[key].minimum_width() + 8))

    def test_ticking_values_in_a_filter_at_its_minimum_does_not_widen_the_column(self):
        browser = self.open(column_widths={"group": 1})
        self.app.update()
        width = browser._header_cells["group"].winfo_width()

        browser.group_box._vars["Kancelar"].set(True)
        browser.group_box._vars["Obchod"].set(True)
        self.app.update()

        self.assertEqual(browser._header_cells["group"].winfo_width(), width)
        self.assertLessEqual(browser.group_box.winfo_reqwidth(), browser._header_cells["group"].winfo_width())
        self.assertTrue(browser.group_box._badge.winfo_ismapped())

    def test_the_filters_scroll_sideways_with_the_table(self):
        browser = self.open(column_widths={"name": 1400, "group": 1400})
        self.app.update()

        browser._scroll_x("moveto", 0.5)
        self.app.update()

        for key, widget in zip((k for k, _, _ in COLUMNS), self.all_filters(browser)):
            if widget.winfo_ismapped():
                self.assertEqual(widget.winfo_rootx(), browser._header_cells[key].winfo_rootx())

    def test_the_filter_row_does_not_start_a_resize_and_its_pointer_is_left_alone(self):
        browser = self.open()
        self.app.update()
        line = browser._header_separators[1].winfo_rootx() + 3  # a zone reaching over the group filter's left edge
        widget = browser.group_box.entry
        cursor = str(widget.cget("cursor"))

        widget.event_generate("<Motion>", x=2, y=2, rootx=line + 5, rooty=widget.winfo_rooty() + 2)
        widget.event_generate("<ButtonPress-1>", x=2, y=2, rootx=line + 5, rooty=widget.winfo_rooty() + 2)

        self.assertEqual(str(widget.cget("cursor")), cursor)
        self.assertIsNone(browser._drag)

    def test_the_columns_are_in_the_agreed_order_with_the_button_first(self):
        browser = self.open()
        self.app.update()

        keys = [key for key, _, _ in COLUMNS]
        self.assertEqual(keys, ["name", "status", "group", "location", "label", "synced", "reported", "note"])
        self.assertEqual([browser._header_cells[k].cget("text").rstrip(" ▲▼") for k in keys],
                         ["Název", "Stav", "Skupina", "Lokace", "Kategorie", "Synchronizováno", "Reportováno",
                          "Poznámka"])
        positions = [browser._header_cells[k].winfo_x() for k in keys]
        self.assertEqual(positions, sorted(positions))
        row = browser._widgets[id(browser._visible[0])]
        self.assertEqual(row[0].cget("text"), "Snímek")
        self.assertLess(row[0].winfo_x() + row[0].winfo_width(), row[1].winfo_x())  # the button is left of the name

    def test_the_button_column_has_a_fixed_width_and_no_resizable_line(self):
        browser = self.open()
        self.app.update()

        first = browser._header_cells["name"].winfo_x()
        self.assertGreaterEqual(first, SNAPSHOT_COLUMN_MINSIZE)
        self.assertNotIn("snapshot", browser.column_widths())
        self.assertEqual(len(browser._header_separators), len(COLUMNS))
        self.assertLess(browser._header_separators[0].winfo_x(), browser._header_separators[1].winfo_x())
        self.assertGreater(browser._header_separators[0].winfo_x(), first)  # the first line is right of "Název"

    def test_a_click_on_a_new_header_sorts_by_it(self):
        browser = self.open()

        for key, expected_first in (("label", "Prerov 2"), ("note", "Prerov 2"), ("reported", "Prerov 1"),
                                    ("synced", "Prerov 1")):
            with self.subTest(column=key):
                browser._header_cells[key].event_generate("<ButtonPress-1>", x=2, y=2, rootx=5000, rooty=10)
                self.assertEqual(browser._sort[0], key)
                self.assertEqual(browser.visible_names()[0], expected_first)
                self.assertTrue(browser._header_cells[key].cget("text").endswith("▲"))

    def test_the_new_columns_can_be_resized_and_their_width_is_saved(self):
        saved = []
        browser = self.open(save_column_widths=saved.append)
        self.app.update()
        separator = browser._header_separators[-1]  # the line after "Poznámka"
        x = separator.winfo_rootx() + 3
        before = browser.column_widths()["note"]

        browser.event_generate("<ButtonPress-1>", x=1, y=1, rootx=x, rooty=100)
        for step in (10, 30):
            separator.event_generate("<B1-Motion>", x=3, y=5, rootx=x + step, rooty=100, state=0x100)
        separator.event_generate("<ButtonRelease-1>", x=3, y=5, rootx=x + 30, rooty=100)

        self.assertEqual(browser.column_widths()["note"], before)  # a press outside the table does not start it
        separator.event_generate("<ButtonPress-1>", x=3, y=5, rootx=x, rooty=100)
        separator.event_generate("<B1-Motion>", x=3, y=5, rootx=x + 40, rooty=100, state=0x100)
        separator.event_generate("<ButtonRelease-1>", x=3, y=5, rootx=x + 40, rooty=100)
        self.assertEqual(browser.column_widths()["note"], before + 40)
        self.assertEqual(saved[-1]["note"], before + 40)

    def test_widths_saved_before_the_new_columns_existed_are_still_valid(self):
        old = {"name": 250, "status": 90, "group": 180, "location": 200, "synced": 150}

        self.assertEqual(valid_widths(old), old)
        browser = self.open(column_widths=old)
        self.assertEqual(browser.column_widths()["name"], 250)
        for key in ("label", "reported", "note"):
            self.assertGreaterEqual(browser.column_widths()[key], MIN_COLUMN_WIDTH)

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
                self.assertEqual(browser._header_cells[key].winfo_x(), first[index + 1].winfo_x())
                self.assertEqual(first[index + 1].winfo_width(), browser._header_cells[key].winfo_width())


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
        self.assertEqual(first[2].winfo_x(), next_x + 60)  # the status cells moved with the header

    def test_dragging_left_narrows_and_stops_at_the_minimum(self):
        browser = self.open()
        before = browser.column_widths()["group"]

        self.drag(browser, "group", -30)
        self.assertEqual(browser.column_widths()["group"], before - 30)
        self.drag(browser, "group", -5000)
        self.assertEqual(browser.column_widths()["group"], browser._min_widths["group"])

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
        row_x = browser._widgets[id(browser._visible[0])][2].winfo_rootx()
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
        self.body_cell = self.browser._widgets[id(self.browser._visible[0])][1]
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
        cell = browser._widgets[id(browser._visible[0])][3]
        before = browser.column_widths()["status"]

        def at(offset, kind, **options):
            cell.event_generate(kind, x=2, y=2, rootx=line + offset, rooty=cell.winfo_rooty() + 2, **options)
        at(0, "<ButtonPress-1>")
        at(15, "<B1-Motion>", state=0x100)
        self.assertEqual(browser.column_widths()["status"], before + 15)  # follows the pointer while held
        at(40, "<B1-Motion>", state=0x100)
        self.assertEqual(browser.column_widths()["status"], before + 40)
        at(-10, "<B1-Motion>", state=0x100)
        self.assertEqual(browser.column_widths()["status"], before - 10)  # and back again
        self.assertEqual(saved, [])
        at(-10, "<ButtonRelease-1>")

        self.assertEqual(saved, [browser.column_widths()])
        at(60, "<B1-Motion>", state=0x100)  # moving without the button changes nothing any more
        self.assertEqual(browser.column_widths()["status"], before - 10)

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


class ColumnVisibilityTest(BrowserTestCase):
    HEADERS = {"group": "Skupina", "location": "Lokace", "label": "Kategorie", "synced": "Synchronizováno",
               "reported": "Reportováno", "note": "Poznámka"}

    @staticmethod
    def fill(button):
        return button._colors.normal if isinstance(button, ColorButton) else str(button.cget("background"))

    def cells(self, browser, key):
        """The header cell and the cells of all the rows of one column."""
        index = [k for k, _, _ in COLUMNS].index(key)
        return [browser._header_cells[key]] + [widgets[index + 1] for widgets in browser._widgets.values()]

    def shown(self, browser, key):
        self.app.update()
        return all(widget.winfo_ismapped() for widget in self.cells(browser, key))

    def hidden(self, browser, key):
        self.app.update()
        return not any(widget.winfo_ismapped() for widget in self.cells(browser, key))

    def test_the_buttons_are_in_the_top_row_right_of_the_other_buttons(self):
        browser = self.open()
        self.app.update()

        buttons = [browser.column_buttons[key] for key in TOGGLE_COLUMNS]
        self.assertEqual(list(browser.column_buttons), ["group", "location", "label", "synced", "reported", "note"])
        self.assertEqual([b.cget("text") for b in buttons], [self.HEADERS[k] for k in TOGGLE_COLUMNS])
        x_positions = [b.winfo_rootx() for b in buttons]
        self.assertEqual(x_positions, sorted(x_positions))
        self.assertGreater(min(x_positions), browser.default_columns_button.winfo_rootx()
                           + browser.default_columns_button.winfo_width())
        top = browser.refresh_button.winfo_rooty()
        for button in buttons:  # in the same row (the heights differ a little)
            self.assertLess(abs(button.winfo_rooty() - top), 12)
            self.assertLess(button.winfo_rooty() + button.winfo_height(), browser.name_entry.winfo_rooty())

    def test_the_section_is_named_and_the_name_and_state_columns_cannot_be_hidden(self):
        browser = self.open()

        labels = [w.cget("text") for w in browser._actions_bar.winfo_children() if isinstance(w, tk.Label)]
        self.assertEqual(labels, ["Zobrazení sloupců:"])
        self.assertNotIn("name", browser.column_buttons)
        self.assertNotIn("status", browser.column_buttons)

    def test_every_button_is_only_as_wide_as_its_text(self):
        browser = self.open()
        from tkinter import font as tkfont
        measure = tkfont.Font(root=self.app, font=self.app.font)

        for key, button in browser.column_buttons.items():
            with self.subTest(column=key):
                text_width = measure.measure(button.cget("text"))
                self.assertLess(button.winfo_reqwidth() - text_width, 50)  # a margin, nothing more

    def test_at_first_every_column_is_shown_and_every_button_is_light_green(self):
        browser = self.open()

        for key, button in browser.column_buttons.items():
            with self.subTest(column=key):
                self.assertTrue(self.shown(browser, key))
                self.assertEqual(self.fill(button), GREEN.normal)
        self.assertEqual(browser.hidden_columns(), [])

    def test_a_click_hides_the_column_with_its_line_and_filter_and_turns_the_button_light_red(self):
        browser = self.open()

        browser.column_buttons["group"].event_generate("<ButtonPress-1>", x=5, y=5)
        browser.column_buttons["group"].event_generate("<ButtonRelease-1>", x=5, y=5)
        self.app.update()

        self.assertTrue(self.hidden(browser, "group"))
        self.assertFalse(browser._header_separators[2].winfo_ismapped())
        self.assertFalse(browser._body_separators[2].winfo_ismapped())
        self.assertFalse(browser.group_box.winfo_ismapped())
        self.assertTrue(browser.location_box.winfo_ismapped())
        self.assertEqual(self.fill(browser.column_buttons["group"]), RED.normal)
        self.assertEqual(self.fill(browser.column_buttons["note"]), GREEN.normal)
        self.assertTrue(self.shown(browser, "note"))

    def test_the_other_columns_move_left_and_come_back_to_their_places(self):
        browser = self.open()
        self.app.update()
        before = {key: browser._header_cells[key].winfo_x() for key, _, _ in COLUMNS}
        width = browser.column_widths()["group"]

        browser.toggle_column("group")
        self.app.update()
        after = {key: browser._header_cells[key].winfo_x() for key, _, _ in COLUMNS}
        self.assertEqual((after["name"], after["status"]), (before["name"], before["status"]))
        self.assertEqual(after["location"], before["group"])  # the next column takes its place
        self.assertEqual(before["note"] - after["note"], width + SEPARATOR_WIDTH)  # its width and its line

        browser.toggle_column("group")
        self.app.update()
        self.assertEqual({key: browser._header_cells[key].winfo_x() for key, _, _ in COLUMNS}, before)
        self.assertTrue(self.shown(browser, "group"))
        self.assertEqual(self.fill(browser.column_buttons["group"]), GREEN.normal)

    def test_the_rows_line_up_with_the_header_when_columns_are_hidden(self):
        browser = self.open()
        browser.toggle_column("location")
        browser.toggle_column("synced")
        self.app.update()

        first_row = browser._widgets[id(browser._visible[0])]
        for index, (key, _, _) in enumerate(COLUMNS):
            if key in ("location", "synced"):
                continue
            with self.subTest(column=key):
                self.assertEqual(browser._header_cells[key].winfo_x(), first_row[index + 1].winfo_x())

    def test_the_table_and_the_scroll_region_get_narrower(self):
        browser = self.open()
        self.app.update()
        full = browser._body.winfo_reqwidth()

        for key in TOGGLE_COLUMNS:
            browser.toggle_column(key)
        self.app.update()

        narrow = browser._body.winfo_reqwidth()
        self.assertLess(narrow, full - 800)
        self.assertEqual(int(browser._canvas.cget("scrollregion").split()[2]), narrow)

    def test_the_first_row_still_shows_when_everything_optional_is_hidden(self):
        browser = self.open()

        for key in TOGGLE_COLUMNS:
            browser.toggle_column(key)

        self.assertEqual(browser.visible_names(), ["Lobby", "Prerov 1", "Prerov 2", "Sklad"])
        self.assertTrue(self.shown(browser, "name"))
        self.assertTrue(self.shown(browser, "status"))

    def test_hiding_a_column_clears_its_filter_and_it_is_not_taken_into_account(self):
        browser = self.open()
        self.tick(browser, browser.group_box, "Obchod")
        self.type_into(browser, browser.note_var, "vchod")
        self.choose(browser.reported_box, "> 1 den")
        self.choose(browser.synced_box, "< 1 minuta")
        self.tick(browser, browser.label_box, "test")
        self.tick(browser, browser.location_box, "Praha")
        self.assertEqual(browser.visible_names(), [])

        for key in ("group", "note", "reported", "synced", "label", "location"):
            browser.toggle_column(key)

        self.assertEqual(len(browser.visible_names()), 4)
        self.assertEqual(browser.status_var.get(), "Zobrazeno 4 z 4")
        for key in ("group", "note", "reported", "synced", "label", "location"):
            browser.toggle_column(key)  # shown again: the filters are empty, not remembered
        self.assertEqual(browser.group_box.checked(), frozenset())
        self.assertEqual(browser.note_var.get(), "")
        self.assertEqual((browser.reported_box.get(), browser.synced_box.get()), ("(vše)", "(vše)"))
        self.assertEqual(len(browser.visible_names()), 4)

    def test_only_the_shown_columns_filter(self):
        browser = self.open()
        self.tick(browser, browser.group_box, "Obchod")
        self.type_into(browser, browser.note_var, "rezerva")
        self.assertEqual(browser.visible_names(), [])

        browser.toggle_column("group")  # the group filter goes, the note filter stays

        self.assertEqual(browser.visible_names(), ["Sklad"])

    def test_a_value_forced_into_a_hidden_filter_is_ignored(self):
        browser = self.open()
        browser.toggle_column("note")

        browser.note_var.set("does not exist")
        browser.apply_filters()

        self.assertEqual(len(browser.visible_names()), 4)
        self.assertEqual(browser._criteria().note, "")

    def test_the_filters_of_hidden_columns_leave_the_row_and_the_rest_stay_above_their_columns(self):
        browser = self.open()
        self.app.update()

        browser.toggle_column("label")
        browser.toggle_column("note")
        self.app.update()

        self.assertFalse(browser.label_box.winfo_ismapped())
        self.assertFalse(browser.note_entry.winfo_ismapped())
        for key in ("name", "status", "group", "location", "synced", "reported"):
            widget, header = browser._filter_widgets[key], browser._header_cells[key]
            with self.subTest(column=key):
                self.assertTrue(widget.winfo_ismapped())
                self.assertEqual((widget.winfo_rootx(), widget.winfo_width()),
                                 (header.winfo_rootx(), header.winfo_width()))

    def test_the_sort_goes_back_to_the_name_when_the_sorted_column_is_hidden(self):
        browser = self.open()
        browser._header_cells["note"].event_generate("<ButtonPress-1>", x=2, y=2, rootx=5000, rooty=10)
        self.assertEqual(browser._sort, ("note", False))

        browser.toggle_column("note")

        self.assertEqual(browser._sort, ("name", False))
        self.assertTrue(browser._header_cells["name"].cget("text").endswith("▲"))
        self.assertEqual(browser.visible_names(), ["Lobby", "Prerov 1", "Prerov 2", "Sklad"])

    def test_hiding_another_column_keeps_the_sort(self):
        browser = self.open()
        browser._header_cells["reported"].event_generate("<ButtonPress-1>", x=2, y=2, rootx=5000, rooty=10)

        browser.toggle_column("note")

        self.assertEqual(browser._sort, ("reported", False))

    def test_reset_does_not_touch_the_shown_columns(self):
        saved = []
        browser = self.open(save_hidden_columns=saved.append)
        browser.toggle_column("group")
        browser.toggle_column("note")
        saved.clear()

        browser.reset_button.invoke()

        self.assertEqual(browser.hidden_columns(), ["group", "note"])
        self.assertTrue(self.hidden(browser, "group"))
        self.assertEqual(self.fill(browser.column_buttons["group"]), RED.normal)
        self.assertEqual(saved, [])

    def test_default_columns_changes_the_widths_and_not_the_shown_columns(self):
        browser = self.open(column_widths={"name": 333})
        browser.toggle_column("location")

        browser.default_columns_button.invoke()

        self.assertEqual(browser.hidden_columns(), ["location"])
        self.assertNotEqual(browser.column_widths()["name"], 333)

    def test_the_hidden_columns_are_reported_in_the_order_of_the_columns_each_time(self):
        saved = []
        browser = self.open(save_hidden_columns=saved.append)

        browser.toggle_column("note")
        browser.toggle_column("group")
        browser.toggle_column("note")

        self.assertEqual(saved, [["note"], ["group", "note"], ["group"]])

    def test_the_hidden_columns_saved_for_the_account_are_hidden_when_the_window_opens(self):
        browser = self.open(hidden_columns=["label", "note"])
        self.app.update()

        self.assertEqual(browser.hidden_columns(), ["label", "note"])
        self.assertTrue(self.hidden(browser, "label"))
        self.assertTrue(self.hidden(browser, "note"))
        self.assertTrue(self.shown(browser, "group"))
        self.assertEqual(self.fill(browser.column_buttons["label"]), RED.normal)
        self.assertEqual(self.fill(browser.column_buttons["group"]), GREEN.normal)
        self.assertEqual(len(browser.visible_names()), 4)
        self.assertTrue(browser.name_entry.winfo_ismapped())

    def test_nonsense_in_the_saved_hidden_columns_is_ignored(self):
        for raw in (None, "note", 5, {"note": 1}, ["name"], ["status", "snapshot"], [None, 3], ["nope"]):
            with self.subTest(raw=raw):
                self.assertEqual(valid_hidden(raw), frozenset())
        self.assertEqual(valid_hidden(["note", "name", "group", "x"]), frozenset({"note", "group"}))
        self.assertEqual(self.open(hidden_columns=["name", "note"]).hidden_columns(), ["note"])

    def test_a_hidden_column_has_no_resize_zone_and_its_neighbour_still_has_one(self):
        browser = self.open(hidden_columns=["location"])
        self.app.update()
        location_line = browser._header_separators[3].winfo_rootx() + 3
        group_line = browser._header_separators[2].winfo_rootx() + 3

        self.assertEqual(browser._edge_at(group_line), "group")
        self.assertNotEqual(browser._edge_at(location_line + 30), "location")
        for x in range(location_line - 8, location_line + 9):
            self.assertNotEqual(browser._edge_at(x), "location")

    def test_widths_are_kept_while_a_column_is_hidden(self):
        browser = self.open(column_widths={"group": 250})

        browser.toggle_column("group")
        browser.toggle_column("group")

        self.assertEqual(browser.column_widths()["group"], 250)
        self.app.update()
        self.assertEqual(browser._header_cells["group"].winfo_width() + 8, 250)

    def test_the_toggle_buttons_have_no_tooltip_trouble_and_survive_a_refresh(self):
        fetch = MagicMock(return_value=PLAYERS)
        browser = self.open(fetch, hidden_columns=["synced"])

        self.advance(browser, 11)
        browser.refresh()
        self.wait_for(lambda: not browser._loading)

        self.assertEqual(browser.hidden_columns(), ["synced"])
        self.assertTrue(self.hidden(browser, "synced"))
        self.assertTrue(self.shown(browser, "reported"))


class ScrollLimitsTest(BrowserTestCase):
    """The table can be scrolled only as far as it is larger than the window; nothing is ever pushed away from its corner."""

    def offset(self, browser):
        """Where the rows are inside their canvas."""
        return (browser._body.winfo_rootx() - browser._canvas.winfo_rootx(),
                browser._body.winfo_rooty() - browser._canvas.winfo_rooty())

    def positions(self, browser):
        """Header cells and filters, from the left edge of the window and the top of their canvases."""
        return ([browser._header_cells[k].winfo_rootx() for k, _, _ in COLUMNS],
                [w.winfo_rootx() for w in browser._filter_widgets.values()],
                browser._header_cells["name"].winfo_rooty() - browser._header_canvas.winfo_rooty(),
                browser._filter_widgets["name"].winfo_rooty() - browser._filter_canvas.winfo_rooty())

    def wheel(self, browser, delta, shift=False):
        cell = browser._widgets[id(browser._visible[0])][1]
        cell.event_generate("<Shift-MouseWheel>" if shift else "<MouseWheel>", delta=delta, x=3, y=3)
        self.app.update()

    def test_a_table_that_fits_does_not_move_whatever_is_scrolled_with_the_wheel(self):
        browser = self.open(hidden_columns=["synced", "note"])
        self.app.update()
        self.assertTrue(browser._fits("x") and browser._fits("y"))
        before = (self.offset(browser), self.positions(browser))

        for delta in (-5, 5, -40, 40):
            self.wheel(browser, delta)
            self.wheel(browser, delta, shift=True)

        self.assertEqual((self.offset(browser), self.positions(browser)), before)
        self.assertEqual(self.offset(browser), (0, 0))

    def test_the_scroll_bars_and_the_code_cannot_push_a_table_that_fits_either(self):
        browser = self.open()
        self.app.update()
        browser.geometry("2400x900")
        self.app.update()
        before = (self.offset(browser), self.positions(browser))

        for args in (("scroll", 3, "units"), ("scroll", -7, "units"), ("moveto", 0.5), ("moveto", 1.0), ("moveto", -0.5)):
            browser._scroll_y(*args)
            browser._scroll_x(*args)
            self.app.update()

        self.assertEqual((self.offset(browser), self.positions(browser)), before)

    def test_a_short_list_is_not_pushed_down_leaving_an_empty_row_below_the_filters(self):
        browser = self.open()
        self.app.update()
        self.assertTrue(browser._fits("y"))
        top = browser._widgets[id(browser._visible[0])][1].winfo_rooty()

        for delta in (-10, -30, 25):
            self.wheel(browser, delta)

        self.assertEqual(browser._widgets[id(browser._visible[0])][1].winfo_rooty(), top)

    def test_a_table_wider_than_the_window_scrolls_and_stops_at_both_ends_without_a_gap(self):
        browser = self.open(column_widths={"name": 1400, "group": 1400})
        self.app.update()
        self.assertFalse(browser._fits("x"))

        browser._scroll_x("moveto", 1.0)
        self.app.update()
        right_edge = browser._body.winfo_rootx() + browser._body.winfo_reqwidth()
        self.assertEqual(right_edge, browser._canvas.winfo_rootx() + browser._canvas.winfo_width())  # no empty band
        for key, widget in zip((k for k, _, _ in COLUMNS), browser._filter_widgets.values()):
            if widget.winfo_ismapped():
                self.assertEqual(widget.winfo_rootx(), browser._header_cells[key].winfo_rootx())
        for _ in range(5):
            self.wheel(browser, -40, shift=True)  # further to the right than there is
        self.assertEqual(browser._body.winfo_rootx() + browser._body.winfo_reqwidth(), right_edge)

        for _ in range(20):
            self.wheel(browser, 40, shift=True)  # and back to the left, further than there is
        self.assertEqual(self.offset(browser)[0], 0)

    def test_a_list_longer_than_the_window_scrolls_down_and_up_and_stops_at_the_ends(self):
        players = [player(f"P{index:03d}", True) for index in range(80)]
        browser = self.open(players=players)
        self.app.update()
        self.assertFalse(browser._fits("y"))

        for _ in range(60):
            self.wheel(browser, 30)  # up, at the top: nothing happens
        self.assertEqual(self.offset(browser)[1], 0)
        browser._scroll_y("moveto", 1.0)
        self.app.update()
        bottom = browser._body.winfo_rooty() + browser._body.winfo_reqheight()
        self.assertEqual(bottom, browser._canvas.winfo_rooty() + browser._canvas.winfo_height())
        for _ in range(30):
            self.wheel(browser, -40)  # down, at the bottom
        self.assertEqual(browser._body.winfo_rooty() + browser._body.winfo_reqheight(), bottom)
        browser._scroll_y("moveto", 0.0)
        self.app.update()
        self.assertEqual(self.offset(browser)[1], 0)

    def test_a_scrolled_table_that_no_longer_needs_scrolling_goes_back_to_its_corner(self):
        browser = self.open(column_widths={"name": 1400, "group": 1400})
        self.app.update()
        browser._scroll_x("moveto", 1.0)
        self.app.update()
        self.assertLess(self.offset(browser)[0], 0)

        for key in ("group", "location", "label", "synced", "reported", "note"):
            browser.toggle_column(key)  # the table is narrower than the window now... but "name" is still 1400 wide
        browser.reset_columns()
        self.app.update()

        self.assertTrue(browser._fits("x"))
        self.assertEqual(self.offset(browser)[0], 0)
        header, filters, _, _ = self.positions(browser)
        self.assertEqual(header[0], filters[0])

    def test_making_the_window_larger_takes_a_scrolled_table_back_to_its_corner(self):
        browser = self.open(column_widths={"name": 800, "group": 500, "location": 400})
        browser.geometry("900x500")
        for _ in range(20):
            self.app.update()
            time.sleep(0.01)
        browser._scroll_x("moveto", 1.0)
        self.app.update()
        self.assertLess(self.offset(browser)[0], 0)
        self.assertFalse(browser._fits("x"))

        browser.geometry(f"{browser._body.winfo_reqwidth() + 100}x500")  # wide enough for the whole table
        for _ in range(30):
            self.app.update()
            time.sleep(0.01)

        self.assertTrue(browser._fits("x"))
        self.assertEqual(self.offset(browser)[0], 0)

    def test_the_header_and_the_filters_scroll_with_the_rows_and_stay_aligned(self):
        browser = self.open(column_widths={"name": 1400, "group": 1400})
        self.app.update()

        for fraction in (0.25, 0.5, 1.0, 0.1):
            browser._scroll_x("moveto", fraction)
            self.app.update()
            for key, widget in zip((k for k, _, _ in COLUMNS), browser._filter_widgets.values()):
                if widget.winfo_ismapped():
                    self.assertEqual(widget.winfo_rootx(), browser._header_cells[key].winfo_rootx())
            first_row = browser._widgets[id(browser._visible[0])]
            self.assertEqual(first_row[2].winfo_rootx(), browser._header_cells["status"].winfo_rootx())


class ResetFiltersTest(BrowserTestCase):
    def test_reset_clears_every_filter_and_shows_all_the_players_again(self):
        browser = self.open()
        browser.name_var.set("lob")
        self.choose(browser.status_box, "Online")
        self.choose(browser.synced_box, "< 1 minuta")
        self.choose(browser.reported_box, "< 1 minuta")
        self.type_into(browser, browser.note_var, "vchod")
        self.tick(browser, browser.group_box, "Kancelar")
        self.tick(browser, browser.location_box, "Praha")
        self.tick(browser, browser.label_box, "vstup")
        self.type_into(browser, browser.label_box.text_var, "vst")
        self.wait_for(lambda: browser.visible_names() == ["Lobby"])

        browser.reset_button.invoke()

        self.assertEqual((browser.name_var.get(), browser.note_var.get()), ("", ""))
        for box in (browser.status_box, browser.synced_box, browser.reported_box):
            self.assertEqual(box.get(), "(vše)")
        for box in (browser.group_box, browser.location_box, browser.label_box):
            self.assertEqual((box.text(), box.checked()), ("", frozenset()))
            self.assertFalse(box._badge.winfo_ismapped())  # the count of ticks is gone
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


class RefreshIntervalTest(BrowserTestCase):
    """
    Two downloads start at least 10 s apart. A press that comes earlier is remembered and its update runs 10 s after
    the previous download started; more presses before that change nothing; when it has run, the next press asks for
    the next update.
    """

    def download(self, browser):
        self.wait_for(lambda: not browser._loading)

    def test_a_press_in_the_first_second_after_an_update_gives_one_update_ten_seconds_after_it(self):
        fetch = MagicMock(return_value=PLAYERS)
        browser = self.open(fetch)  # the download of the opening: t = 0
        self.advance(browser, 1)

        browser.refresh_button.invoke()

        self.assertEqual(fetch.call_count, 1)  # nothing yet
        self.assertTrue(browser._pending)
        self.advance(browser, 8.9)  # t = 9.9
        self.assertEqual(fetch.call_count, 1)
        self.advance(browser, 0.1)  # t = 10
        self.download(browser)
        self.assertEqual(fetch.call_count, 2)
        self.assertFalse(browser._pending)

    def test_more_presses_while_it_waits_change_nothing(self):
        fetch = MagicMock(return_value=PLAYERS)
        browser = self.open(fetch)
        self.advance(browser, 1)
        browser.refresh_button.invoke()

        for second in range(2, 10):  # the 2nd, 3rd ... 9th second
            self.advance(browser, 1)
            browser.refresh_button.invoke()
            browser.refresh()
            self.assertEqual(fetch.call_count, 1)
        self.advance(browser, 1)  # the 10th second
        self.download(browser)

        self.assertEqual(fetch.call_count, 2)  # one update for all those presses
        self.advance(browser, 0)
        self.app.update()
        self.assertEqual(fetch.call_count, 2)  # and not another one afterwards

    def test_when_the_update_has_run_the_requests_are_cleared_and_a_press_asks_for_the_next_update(self):
        fetch = MagicMock(return_value=PLAYERS)
        browser = self.open(fetch)
        self.advance(browser, 1)
        browser.refresh_button.invoke()
        self.advance(browser, 9)
        self.download(browser)
        self.assertEqual(fetch.call_count, 2)
        self.assertFalse(browser._pending)

        self.advance(browser, 2)  # t = 12: the second update started at t = 10
        browser.refresh_button.invoke()
        self.assertTrue(browser._pending)
        self.advance(browser, 7.9)  # t = 19.9
        self.assertEqual(fetch.call_count, 2)
        self.advance(browser, 0.1)  # t = 20
        self.download(browser)

        self.assertEqual(fetch.call_count, 3)

    def test_a_press_when_the_interval_is_over_updates_at_once(self):
        fetch = MagicMock(return_value=PLAYERS)
        browser = self.open(fetch)
        self.advance(browser, 10)

        browser.refresh_button.invoke()
        self.download(browser)

        self.assertEqual(fetch.call_count, 2)
        self.assertFalse(browser._pending)

    def test_a_press_fifteen_seconds_after_the_previous_update_waits_for_nothing(self):
        fetch = MagicMock(return_value=PLAYERS)
        browser = self.open(fetch)
        self.advance(browser, 15)

        browser.refresh_button.invoke()

        self.assertFalse(browser._pending)  # nothing is remembered, the update starts at once
        self.download(browser)
        self.assertEqual(fetch.call_count, 2)
        self.assertNotIn("aktualizace za", browser.updated_var.get())

    def test_the_fifteen_seconds_are_counted_from_the_start_of_the_previous_update(self):
        fetch = MagicMock(return_value=PLAYERS)
        browser = self.open(fetch)  # the update at t = 0
        self.advance(browser, 3)
        browser.refresh_button.invoke()
        self.advance(browser, 7)  # t = 10: the asked-for update runs
        self.download(browser)
        self.assertEqual(fetch.call_count, 2)

        self.advance(browser, 15)  # t = 25: 15 s after the update that started at t = 10
        browser.refresh_button.invoke()
        self.download(browser)

        self.assertEqual(fetch.call_count, 3)  # at once, without waiting

    def test_a_press_while_a_download_is_running_counts_like_any_early_press(self):
        release = threading.Event()
        calls = []

        def fetch(*_):
            calls.append(1)
            if len(calls) == 1:
                release.wait(5)
            return PLAYERS
        browser = PlayerBrowser(self.app, url="u", login="l", password="p", account_name="A", fetch=fetch)
        self.addCleanup(browser.destroy)
        self.wait_for(lambda: len(calls) == 1)  # the first download is running (t = 0)
        self.clock[0] += 1

        browser.refresh_button.invoke()  # pressed during the download
        release.set()
        self.wait_for(lambda: not browser._loading)

        self.assertEqual(len(calls), 1)
        self.advance(browser, 9)
        self.wait_for(lambda: len(calls) == 2)

    def test_a_download_that_lasts_longer_than_the_interval_is_followed_at_once_by_the_asked_update(self):
        release = threading.Event()
        calls = []

        def fetch(*_):
            calls.append(1)
            if len(calls) == 1:
                release.wait(5)
            return PLAYERS
        browser = PlayerBrowser(self.app, url="u", login="l", password="p", account_name="A", fetch=fetch)
        self.addCleanup(browser.destroy)
        self.wait_for(lambda: len(calls) == 1)
        self.clock[0] += 15  # the download has lasted 15 s, the interval is over
        browser.refresh_button.invoke()
        self.assertEqual(len(calls), 1)  # still one running: the press waits for it
        self.assertTrue(browser._pending)

        release.set()

        self.wait_for(lambda: len(calls) == 2)

    def test_the_wait_is_shown_as_a_countdown_only_while_an_update_is_asked_for(self):
        browser = self.open()
        self.assertRegex(browser.updated_var.get(), r"^Aktualizováno \d\d:\d\d:\d\d$")  # nothing asked for: nothing

        self.advance(browser, 1)
        browser.refresh_button.invoke()
        self.assertRegex(browser.updated_var.get(), r"^Aktualizováno \d\d:\d\d:\d\d · aktualizace za 9 s$")
        self.advance(browser, 3.5)
        self.assertRegex(browser.updated_var.get(), r" · aktualizace za 6 s$")
        self.advance(browser, 5.5)
        self.download(browser)
        self.assertNotIn("aktualizace za", browser.updated_var.get())

    def test_the_countdown_and_the_update_come_by_themselves(self):
        fetch = MagicMock(return_value=PLAYERS)
        browser = self.open(fetch)
        browser.refresh_button.invoke()
        self.assertIn("za 10 s", browser.updated_var.get())

        self.clock[0] += 4
        self.wait_for(lambda: "za 6 s" in browser.updated_var.get())
        self.clock[0] += 6
        self.wait_for(lambda: fetch.call_count == 2)
        self.download(browser)
        self.assertNotIn("aktualizace za", browser.updated_var.get())

    def test_the_button_is_always_on(self):
        browser = self.open()

        self.assertTrue(browser.refresh_button.instate(["!disabled"]))
        browser.refresh_button.invoke()
        self.assertTrue(browser.refresh_button.instate(["!disabled"]))

    def test_the_interval_runs_from_the_start_of_a_download_not_from_its_end(self):
        fetch = MagicMock(side_effect=lambda *_: (self.clock.__setitem__(0, self.clock[0] + 4), PLAYERS)[1])
        browser = self.open(fetch)  # started at 0, ended at 4
        browser.refresh_button.invoke()

        self.assertIn("za 6 s", browser.updated_var.get())  # 10 s from the start minus the 4 s the download took

    def test_a_failed_download_starts_the_interval_too_and_a_press_still_gets_its_update(self):
        fetch = MagicMock(side_effect=[requests.exceptions.ConnectionError(), PLAYERS])
        browser = self.open(fetch)
        self.advance(browser, 2)
        browser.refresh_button.invoke()
        self.assertEqual(fetch.call_count, 1)

        self.advance(browser, 8)
        self.download(browser)

        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(len(browser.visible_names()), 4)

    def test_the_players_and_the_filters_stay_usable_while_an_update_waits(self):
        browser = self.open()
        self.advance(browser, 1)
        browser.refresh_button.invoke()

        browser.name_var.set("lobby")
        self.wait_for(lambda: browser.visible_names() == ["Lobby"])

        self.assertEqual(browser.status_var.get(), "Zobrazeno 1 z 4")
        self.assertIn("aktualizace za", browser.updated_var.get())

    def test_closing_the_window_while_an_update_waits_raises_nothing(self):
        browser = self.open()
        browser.refresh_button.invoke()

        browser.destroy()
        for _ in range(30):
            self.app.update()
            time.sleep(0.01)

    def test_the_update_that_runs_shows_the_new_data_and_time(self):
        changed = [dict(p) for p in PLAYERS]
        changed[1] = {**changed[1], "isConnected": True, "notes": "opraveno"}
        fetch = MagicMock(side_effect=[PLAYERS, changed])
        browser = self.open(fetch)
        self.advance(browser, 1)
        browser.refresh_button.invoke()
        self.advance(browser, 9)
        self.download(browser)

        row = next(r for r in browser._rows if r.name == "Prerov 1")
        self.assertTrue(row.online)
        cells = [w.cget("text") for w in browser._widgets[id(row)][1:]]
        self.assertEqual((cells[1], cells[7]), ("Online", "opraveno"))
        self.assertEqual(len(browser._widgets), 4)  # the old rows are gone, not piled up
        self.assertRegex(browser.updated_var.get(), r"^Aktualizováno \d\d:\d\d:\d\d$")

    def test_after_a_failed_update_the_old_players_stay_and_it_says_when_they_are_from(self):
        answers = [PLAYERS, requests.exceptions.ConnectionError(), PLAYERS + [player("Novy")]]

        def fetch(*_):
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        browser = self.open(fetch)
        first_time = browser.updated_var.get().split(" · ")[0].split()[-1]
        normal = str(browser._status_label.cget("foreground"))

        self.advance(browser, 10)
        browser.refresh_button.invoke()
        self.download(browser)

        self.assertEqual(len(browser.visible_names()), 4)  # the players of the first download are still there
        self.assertTrue(browser.status_var.get().startswith("Playery se nepodařilo načíst"))
        self.assertNotEqual(str(browser._status_label.cget("foreground")), normal)  # in red
        self.assertIn(f"Zobrazená data jsou z {first_time}", browser.updated_var.get())
        browser.name_var.set("lobby")  # using a filter must not make the old data look current
        self.wait_for(lambda: browser.visible_names() == ["Lobby"])
        self.assertNotEqual(str(browser._status_label.cget("foreground")), normal)
        self.assertIn("Zobrazená data jsou z", browser.updated_var.get())

        self.advance(browser, 10)
        browser.refresh_button.invoke()
        self.download(browser)
        self.assertEqual(str(browser._status_label.cget("foreground")), normal)
        self.assertRegex(browser.updated_var.get(), r"^Aktualizováno ")
        browser.name_var.set("")
        self.wait_for(lambda: len(browser.visible_names()) == 5)

    def test_a_failure_at_the_very_first_download_shows_no_time(self):
        fetch = MagicMock(side_effect=requests.exceptions.ConnectionError())
        browser = self.open(fetch)

        self.assertNotIn("Zobrazená data", browser.updated_var.get())
        self.assertNotIn("Aktualizováno", browser.updated_var.get())


class LogoutTest(unittest.TestCase):
    """What was downloaded stays valid whatever the server answers to the logout."""

    def test_a_logout_the_server_answers_unexpectedly_does_not_lose_the_players(self):
        from gui_app.player_browser import fetch_players_from_server
        server = MagicMock()
        server.get_player_objects.return_value = [{"name": "a"}]
        server.close_quietly.side_effect = None
        with patch("gui_app.player_browser.ServerApi", return_value=server):
            self.assertEqual(fetch_players_from_server("https://x", "l", "p"), [{"name": "a"}])
        server.close_quietly.assert_called_once()

    def test_the_logout_is_still_tried_when_the_download_fails(self):
        from gui_app.player_browser import fetch_players_from_server
        server = MagicMock()
        server.get_player_objects.side_effect = requests.exceptions.Timeout()
        with patch("gui_app.player_browser.ServerApi", return_value=server):
            with self.assertRaises(requests.exceptions.Timeout):
                fetch_players_from_server("https://x", "l", "p")
        server.close_quietly.assert_called_once()

    def test_close_quietly_swallows_the_errors_of_the_logout_only(self):
        api = ServerApi.__new__(ServerApi)
        for error in (ResponseError({"params": {}}), requests.exceptions.ConnectionError(), requests.exceptions.Timeout()):
            api._make_request = MagicMock(side_effect=error)
            api._session_token = "t"
            api.close_quietly()
            self.assertIsNone(api._session_token)  # the token is dropped in any case
        api._make_request = MagicMock(side_effect=ValueError("a real bug"))
        with self.assertRaises(ValueError):
            api.close_quietly()

    def test_the_answer_of_the_swagger_test_server_to_a_logout_is_not_an_error_for_the_download(self):
        """It answers {"status": "Success"}: no "success" key, which the request helper treats as a failure."""
        api = ServerApi.__new__(ServerApi)
        api._url, api._assert_hostname, api._session_token = "https://x/api", None, "t"
        response = MagicMock(ok=True)
        response.json.return_value = {"status": "Success"}
        with patch("api_testing.request_calls.requests.request", return_value=response):
            api.close_quietly()


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
                self.advance(browser, 11)
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
        self.advance(browser, 11)
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

    def test_the_hidden_columns_are_remembered_per_account(self):
        self.app.all_data["logins"]["Demo"] = {"url": "https://x", "names": {"jane": {"login": "jane"}},
                                               "player_hidden": ["note"]}
        self.app.all_data["logins"]["Other"] = {"url": "https://y", "names": {}}
        self.app.account_data = self.app.all_data["logins"]
        self.app.save_account_configs()
        self.app.option_choose_administration.set("Demo")
        with patch("gui_app.gui.PlayerBrowser") as browser_class:
            self.app.open_player_browser("https://x", "jane", "pw")
            options = browser_class.call_args.kwargs
            self.assertEqual(options["hidden_columns"], ["note"])

            options["save_hidden_columns"](["group", "note"])

        with open(self.app.config_file, encoding="utf-8") as file:
            saved = json.load(file)["logins"]
        self.assertEqual(saved["Demo"]["player_hidden"], ["group", "note"])
        self.assertNotIn("player_hidden", saved["Other"])
        options["save_hidden_columns"]([])  # everything shown again
        with open(self.app.config_file, encoding="utf-8") as file:
            self.assertNotIn("player_hidden", json.load(file)["logins"]["Demo"])

    def test_the_hidden_columns_and_the_widths_are_stored_side_by_side(self):
        self.app.all_data["logins"]["Demo"] = {"url": "https://x", "names": {}}
        self.app.account_data = self.app.all_data["logins"]
        self.app.save_account_configs()

        self.app.save_player_columns("Demo", {"name": 300})
        self.app.save_hidden_player_columns("Demo", ["label"])
        self.app.save_player_columns("Demo", {})

        with open(self.app.config_file, encoding="utf-8") as file:
            entry = json.load(file)["logins"]["Demo"]
        self.assertEqual(entry["player_hidden"], ["label"])
        self.assertNotIn("player_columns", entry)

    def test_saving_hidden_columns_for_a_removed_account_writes_nothing(self):
        self.app.save_hidden_player_columns("Gone", ["note"])

        with open(self.app.config_file, encoding="utf-8") as file:
            self.assertEqual(json.load(file)["logins"], {})

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
