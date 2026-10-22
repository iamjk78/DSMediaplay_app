import gc
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
from unittest.mock import MagicMock, call, patch

import requests

from api_testing.request_calls import LoginError, ResponseError, ServerApi
from button_helpers import fill, font_of, press
from gui_app import gui
from gui_app.color_button import GREEN, RED, ColorButton, button_interactive
from gui_app.snapshot_viewer import DEFAULT_WINDOW_SIZE
from gui_app.player_browser import (COLUMNS, EDGE_ZONE, MAX_COLUMN_WIDTH, MIN_COLUMN_WIDTH, RESIZE_CURSOR, ROW_PADY,
                                    SEPARATOR_COLOR, SEPARATOR_WIDTH, SNAPSHOT_COLUMN_MINSIZE, SORT_CURSOR, TOGGLE_COLUMNS,
                                    PlayerBrowser, valid_hidden, valid_widths, valid_window_geometry)
from util.language import LanguageManager

ACTION = "show_player_snapshots"


def player(name, connected=True, group="Obchod", location="Praha", labels=(), uploaded=0, reported=0, notes="",
           temperature=None, version=""):
    result = {"_id": f"id-{name}", "name": name, "isConnected": connected, "group": {"name": group} if group else None,
              "configLocation": location, "labels": list(labels), "lastUpload": uploaded, "lastReported": reported,
              "notes": notes}
    if temperature is not None:
        result["piTemperature"] = temperature
    if version:
        result["version"] = version
    return result


def ago(**delta):
    return int((datetime.now() - timedelta(**delta)).timestamp() * 1000)


def make_players():
    return [
        player("Lobby", True, "Kancelar", "Praha", ["vstup"], uploaded=ago(seconds=30), reported=ago(seconds=20),
               notes="hlavní vchod", temperature="47.2", version="5.3.1"),
        player("Prerov 1", False, "Obchod", "Prerov", ["vstup", "test"], uploaded=ago(days=40),
               reported=ago(days=2), notes="rozbitá\nobrazovka", temperature="63", version="5.10.2"),
        player("Prerov 2", True, "Obchod", "Prerov", reported=ago(minutes=3), temperature="81", version="5.3.1"),
        player("Sklad", True, None, "", notes="rezerva"),
    ]


PLAYERS = make_players()  # refreshed for every test: the times in it are relative to now


class BrowserTestCase(unittest.TestCase):
    def setUp(self):
        gc.collect()  # Tk variables of earlier tests are freed here, not by a worker thread (that call would wait)
        self.addCleanup(gc.collect)
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
        options.setdefault("hidden_columns", [])  # every column shown, unless a test asks for something else
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
        cells = {row.name: [w for w in browser.widgets_for(row)[1:]] for row in browser._rows}  # without the button

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

    def test_every_row_has_a_snapshot_button(self):
        browser = self.open()

        buttons = [widgets[0] for widgets, row in zip(browser._pool, browser._pool_rows) if row is not None]
        self.assertEqual(len(buttons), 4)
        for button in buttons:
            self.assertEqual(button.cget("text"), "Snímek")

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

        first_row = browser.widgets_for(browser._visible[0])
        for index, (key, _, _) in enumerate(COLUMNS):
            with self.subTest(column=key):
                self.assertEqual(browser._header_cells[key].winfo_x(), first_row[index + 1].winfo_x())

    def test_the_window_is_wide_enough_for_the_table(self):
        browser = self.open(hidden_columns=["temperature", "version"])
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
            self.assertGreater(widget.winfo_rootx(), browser.widgets_for(browser._visible[0])[0].winfo_rootx()
                               + browser.widgets_for(browser._visible[0])[0].winfo_width() - 1)
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
        self.assertEqual(keys, ["name", "status", "group", "location", "label", "synced", "reported", "note",
                                "temperature", "version"])
        self.assertEqual([browser._header_cells[k].cget("text").rstrip(" ▲▼") for k in keys],
                         ["Název", "Stav", "Skupina", "Lokace", "Kategorie", "Synchronizováno", "Reportováno",
                          "Poznámka", "Teplota", "Verze"])
        positions = [browser._header_cells[k].winfo_x() for k in keys]
        self.assertEqual(positions, sorted(positions))
        row = browser.widgets_for(browser._visible[0])
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
        separator = browser._header_separators[[k for k, _, _ in COLUMNS].index("note")]  # the line after "Poznámka"
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
        rows_height = max(w.winfo_y() + w.winfo_height() for w in browser.widgets_for(browser._visible[-1]))
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

        first = browser.widgets_for(browser._visible[0])
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
        first = browser.widgets_for(browser._visible[0])
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
        row_x = browser.widgets_for(browser._visible[0])[2].winfo_rootx()
        self.assertEqual(header_x, row_x)  # still lined up after scrolling

    def test_the_horizontal_scroll_bar_is_hidden_while_everything_fits(self):
        browser = self.open(hidden_columns=["temperature", "version"])
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
        self.body_cell = self.browser.widgets_for(self.browser._visible[0])[1]
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
        cell = browser.widgets_for(browser._visible[0])[3]
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
               "reported": "Reportováno", "note": "Poznámka", "temperature": "Teplota", "version": "Verze"}

    @staticmethod
    def fill(button):
        return button._colors.normal if isinstance(button, ColorButton) else str(button.cget("background"))

    def cells(self, browser, key):
        """The header cell and the cells of all the rows of one column."""
        index = [k for k, _, _ in COLUMNS].index(key)
        return [browser._header_cells[key]] + [
            widgets[index + 1] for widgets, row in zip(browser._pool, browser._pool_rows) if row is not None]

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
        self.assertEqual(list(browser.column_buttons), ["group", "location", "label", "synced", "reported", "note",
                                                        "temperature", "version"])
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

        labels = [w.cget("text") for w in browser._toggle_group.winfo_children() if isinstance(w, tk.Label)]
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

        first_row = browser.widgets_for(browser._visible[0])
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

    @staticmethod
    def space_below_last_player(browser):
        """Pixels between the bottom of the row of the last player and the bottom edge of the table: a negative
        number is how much of that row is cut off (or, when it is large, entirely out of sight)."""
        widgets = browser.widgets_for(browser._visible[-1])
        if widgets is None:
            return -10 ** 6  # not even in the pool
        row_bottom = max(widget.winfo_rooty() + widget.winfo_height() for widget in widgets[:2])
        return browser._canvas.winfo_rooty() + browser._canvas.winfo_height() - row_bottom

    def wheel(self, browser, delta, shift=False):
        cell = browser._pool[0][1]  # any row cell that is currently on screen, wherever the pool has scrolled to
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
        top = browser.widgets_for(browser._visible[0])[1].winfo_rooty()

        for delta in (-10, -30, 25):
            self.wheel(browser, delta)

        self.assertEqual(browser.widgets_for(browser._visible[0])[1].winfo_rooty(), top)

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
        """The rows are a pool, not a scrolled canvas (see the class docstring): scrolling moves _first_index, the
        offset of the pool inside _canvas never changes at all any more."""
        players = [player(f"P{index:03d}", True) for index in range(80)]
        browser = self.open(players=players)
        self.app.update()
        self.assertFalse(browser._fits("y"))
        last_page = len(browser._visible) - browser._whole_rows

        for _ in range(60):
            self.wheel(browser, 30)  # up, at the top: nothing happens
        self.assertEqual(browser._first_index, 0)
        self.assertEqual(self.offset(browser)[1], 0)

        browser._scroll_y("moveto", 1.0)
        self.app.update()
        self.assertEqual(browser._first_index, last_page)
        shown = [row for row in browser._pool_rows if row is not None]
        self.assertEqual(shown[-1].name, "P079")  # the last player really is the last one that is shown
        self.assertGreaterEqual(self.space_below_last_player(browser), 0)  # ... and it is entirely on the screen
        self.assertEqual(self.offset(browser)[1], 0)

        for _ in range(30):
            self.wheel(browser, -40)  # down, further than there is: stays at the bottom
        self.assertEqual(browser._first_index, last_page)

        browser._scroll_y("moveto", 0.0)
        self.app.update()
        self.assertEqual(browser._first_index, 0)

    def test_the_last_player_is_entirely_visible_whatever_the_height_of_the_window(self):
        """The pool used to have more rows than fit and the rows were taller than it thought, so the last five or so
        players could never be scrolled into view."""
        browser = self.open(players=[player(f"P{index:03d}", True) for index in range(120)])
        for height in (330, 450, 520, 700, 910):
            with self.subTest(height=height):
                browser.geometry(f"1300x{height}")
                self.app.update()
                browser._scroll_y("moveto", 1.0)
                self.app.update()

                self.assertEqual(browser.visible_names()[-1], "P119")
                self.assertGreaterEqual(self.space_below_last_player(browser), 0)

    def test_a_list_only_a_little_longer_than_the_window_can_still_be_scrolled_to_its_end(self):
        probe = self.open(players=[player("P000", True)])
        probe.geometry("1300x450")
        self.app.update()
        whole, pool = probe._whole_rows, probe._pool_size
        probe.destroy()

        for count in (whole, whole + 1, whole + 2, pool, pool + 1):
            with self.subTest(players=count):
                browser = self.open(players=[player(f"P{index:03d}", True) for index in range(count)])
                browser.geometry("1300x450")
                self.app.update()
                browser._scroll_y("moveto", 1.0)
                self.app.update()

                self.assertEqual(browser._fits("y"), count <= whole)
                self.assertGreaterEqual(self.space_below_last_player(browser), 0)
                browser.destroy()

    def test_the_scroll_bar_reaches_the_bottom_exactly_when_the_last_player_is_in_view(self):
        browser = self.open(players=[player(f"P{index:03d}", True) for index in range(120)])
        browser.geometry("1300x450")
        self.app.update()

        browser._scroll_y("moveto", 1.0)
        self.app.update()

        first, last = browser._scrollbar.get()
        self.assertAlmostEqual(last, 1.0)
        self.assertAlmostEqual(last - first, browser._whole_rows / 120)

        browser._scroll_y("moveto", 0.0)  # the thumb is as long as the part of the list that is entirely in view
        self.app.update()
        first, last = browser._scrollbar.get()
        self.assertAlmostEqual(first, 0.0)
        self.assertAlmostEqual(last, browser._whole_rows / 120)

    def test_a_page_is_as_many_rows_as_are_entirely_visible(self):
        browser = self.open(players=[player(f"P{index:03d}", True) for index in range(120)])
        browser.geometry("1300x450")
        self.app.update()

        browser._scroll_y("scroll", 1, "pages")

        self.assertEqual(browser._first_index, browser._whole_rows)

    def test_the_height_of_a_row_is_that_of_its_tallest_widget(self):
        browser = self.open(players=[player(f"P{index:03d}", True) for index in range(5)])
        self.app.update()
        button, first_cell = browser._pool[0][0], browser._pool[0][1]

        self.assertGreaterEqual(browser._row_height(), button.winfo_reqheight() + 2 * ROW_PADY)
        self.assertGreater(button.winfo_reqheight(), first_cell.winfo_reqheight())  # why a cell is not enough
        self.assertEqual(browser._row_height(), browser._body.grid_bbox(0, 1)[3])  # what the grid really uses

    def test_the_last_player_stays_in_view_after_the_window_is_made_smaller_and_after_the_font_is_made_larger(self):
        browser = self.open(players=[player(f"P{index:03d}", True) for index in range(120)])
        browser.geometry("1300x800")
        self.app.update()
        browser.geometry("1300x400")  # the pool made for the large window is not taken away again
        self.app.update()

        browser._scroll_y("moveto", 1.0)
        self.app.update()
        self.assertGreaterEqual(self.space_below_last_player(browser), 0)

        browser.change_font_size(4)
        self.app.update()
        browser._scroll_y("moveto", 1.0)
        self.app.update()
        self.assertGreaterEqual(self.space_below_last_player(browser), 0)

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
            first_row = browser.widgets_for(browser._visible[0])
            self.assertEqual(first_row[2].winfo_rootx(), browser._header_cells["status"].winfo_rootx())


class TemperatureAndVersionTest(BrowserTestCase):
    def cell(self, browser, name, key):
        row = next(r for r in browser._rows if r.name == name)
        return browser.widgets_for(row)[1 + [k for k, _, _ in COLUMNS].index(key)].cget("text")

    def test_they_are_the_last_two_columns_and_have_switches_at_the_end_of_the_row(self):
        browser = self.open()

        self.assertEqual([k for k, _, _ in COLUMNS][-2:], ["temperature", "version"])
        self.assertEqual(list(browser.column_buttons)[-2:], ["temperature", "version"])
        self.assertEqual([browser.column_buttons[k].cget("text") for k in ("temperature", "version")], ["Teplota", "Verze"])
        self.app.update()
        self.assertLess(browser.column_buttons["note"].winfo_rootx(), browser.column_buttons["temperature"].winfo_rootx())
        self.assertLess(browser.column_buttons["temperature"].winfo_rootx(), browser.column_buttons["version"].winfo_rootx())

    def test_both_are_off_by_default_and_their_switches_are_red(self):
        browser = self.open(hidden_columns=None)
        self.app.update()

        self.assertEqual(browser.hidden_columns(), ["temperature", "version"])
        for key in ("temperature", "version"):
            self.assertFalse(browser._header_cells[key].winfo_ismapped())
            self.assertFalse(browser._filter_widgets[key].winfo_ismapped())
            self.assertEqual(fill(browser.column_buttons[key]), RED.normal)
        for key in ("group", "location", "label", "synced", "reported", "note"):
            self.assertTrue(browser._header_cells[key].winfo_ismapped())

    def test_switching_them_on_shows_the_columns_and_the_filters_at_the_end(self):
        browser = self.open(hidden_columns=None)

        browser.toggle_column("temperature")
        browser.toggle_column("version")
        self.app.update()

        self.assertEqual(browser.hidden_columns(), [])
        note, temperature, version = (browser._header_cells[k].winfo_x() for k in ("note", "temperature", "version"))
        self.assertLess(note, temperature)
        self.assertLess(temperature, version)
        for key in ("temperature", "version"):
            widget, header = browser._filter_widgets[key], browser._header_cells[key]
            self.assertEqual((widget.winfo_rootx(), widget.winfo_width()), (header.winfo_rootx(), header.winfo_width()))

    def test_the_temperature_is_shown_in_degrees_and_the_version_as_it_is(self):
        browser = self.open()

        self.assertEqual(self.cell(browser, "Lobby", "temperature"), "47.2 °C")
        self.assertEqual(self.cell(browser, "Prerov 1", "temperature"), "63 °C")
        self.assertEqual(self.cell(browser, "Sklad", "temperature"), "")  # the player does not say
        self.assertEqual(self.cell(browser, "Lobby", "version"), "5.3.1")
        self.assertEqual(self.cell(browser, "Sklad", "version"), "")

    def test_the_temperature_filter_offers_hotter_than_and_no_data(self):
        browser = self.open()

        self.assertEqual(list(browser.temperature_box["values"]),
                         ["(vše)", "> 50 °C", "> 60 °C", "> 70 °C", "> 80 °C", "bez údaje"])

    def test_the_temperature_filter(self):
        browser = self.open()

        self.choose(browser.temperature_box, "> 50 °C")
        self.assertEqual(browser.visible_names(), ["Prerov 1", "Prerov 2"])
        self.choose(browser.temperature_box, "> 80 °C")
        self.assertEqual(browser.visible_names(), ["Prerov 2"])
        self.choose(browser.temperature_box, "> 60 °C")
        self.assertEqual(browser.visible_names(), ["Prerov 1", "Prerov 2"])
        self.choose(browser.temperature_box, "bez údaje")
        self.assertEqual(browser.visible_names(), ["Sklad"])
        self.choose(browser.temperature_box, "(vše)")
        self.assertEqual(len(browser.visible_names()), 4)

    def test_the_version_filter_takes_ticks_and_text_and_offers_the_versions_the_account_has(self):
        browser = self.open()

        self.assertEqual([label for label, _ in browser.version_box._choices], ["5.3.1", "5.10.2"])  # 5.10 is after 5.3
        self.tick(browser, browser.version_box, "5.3.1")
        self.assertEqual(browser.visible_names(), ["Lobby", "Prerov 2"])
        self.tick(browser, browser.version_box, "5.10.2")
        self.assertEqual(browser.visible_names(), ["Lobby", "Prerov 1", "Prerov 2"])
        self.tick(browser, browser.version_box, "5.3.1", "5.10.2", on=False)
        self.type_into(browser, browser.version_box.text_var, "5.10")
        self.assertEqual(browser.visible_names(), ["Prerov 1"])

    def test_they_sort_by_the_number_and_by_the_version_numbers(self):
        browser = self.open()

        browser._header_cells["temperature"].event_generate("<ButtonPress-1>", x=2, y=2, rootx=5000, rooty=10)
        self.assertEqual(browser.visible_names(), ["Lobby", "Prerov 1", "Prerov 2", "Sklad"])  # 47.2, 63, 81, none
        browser._header_cells["temperature"].event_generate("<ButtonPress-1>", x=2, y=2, rootx=5000, rooty=10)
        self.assertEqual(browser.visible_names(), ["Prerov 2", "Prerov 1", "Lobby", "Sklad"])  # a player without a value stays last
        browser._header_cells["version"].event_generate("<ButtonPress-1>", x=2, y=2, rootx=5000, rooty=10)
        self.assertEqual(browser.visible_names(), ["Lobby", "Prerov 2", "Prerov 1", "Sklad"])  # 5.3.1, 5.3.1, 5.10.2, none

    def test_hiding_them_clears_their_filters_and_they_stop_counting(self):
        browser = self.open()
        self.choose(browser.temperature_box, "> 80 °C")
        self.tick(browser, browser.version_box, "5.3.1")
        self.assertEqual(browser.visible_names(), ["Prerov 2"])

        browser.toggle_column("temperature")
        browser.toggle_column("version")

        self.assertEqual(len(browser.visible_names()), 4)
        browser.toggle_column("temperature")
        browser.toggle_column("version")
        self.assertEqual((browser.temperature_box.get(), browser.version_box.checked(), browser.version_box.text()),
                         ("(vše)", frozenset(), ""))

    def test_reset_clears_their_filters_too_and_leaves_the_switches(self):
        browser = self.open()
        self.choose(browser.temperature_box, "> 50 °C")
        self.tick(browser, browser.version_box, "5.3.1")
        self.type_into(browser, browser.version_box.text_var, "5")

        browser.reset_button.invoke()

        self.assertEqual((browser.temperature_box.get(), browser.version_box.checked(), browser.version_box.text()),
                         ("(vše)", frozenset(), ""))
        self.assertEqual(browser.hidden_columns(), [])
        self.assertEqual(len(browser.visible_names()), 4)

    def test_the_filters_combine_with_the_others(self):
        browser = self.open()
        self.choose(browser.temperature_box, "> 50 °C")
        self.tick(browser, browser.group_box, "Obchod")
        self.choose(browser.status_box, "Online")

        self.assertEqual(browser.visible_names(), ["Prerov 2"])

    def test_their_widths_can_be_set_and_are_kept(self):
        saved = []
        browser = self.open(column_widths={"temperature": 150, "version": 200}, save_column_widths=saved.append)

        self.assertEqual((browser.column_widths()["temperature"], browser.column_widths()["version"]), (150, 200))
        browser.set_font_size(18)
        self.assertEqual((browser.column_widths()["temperature"], browser.column_widths()["version"]), (225, 300))

    def test_the_switches_go_below_the_buttons_on_a_screen_too_narrow_for_one_row(self):
        with patch.object(tk.Misc, "winfo_screenwidth", return_value=900):
            browser = self.open()
            self.app.update()

            self.assertGreater(browser._toggle_group.winfo_rooty(), browser.refresh_button.winfo_rooty())
            self.assertFalse(browser._toggle_separator.winfo_ismapped())
            for button in browser.column_buttons.values():
                self.assertLessEqual(button.winfo_rootx() + button.winfo_width(),
                                     browser._actions_bar.winfo_rootx() + browser._actions_bar.winfo_width() + 1)

    def test_the_switches_stand_right_of_the_buttons_on_a_wide_screen(self):
        with patch.object(tk.Misc, "winfo_screenwidth", return_value=3000):
            browser = self.open()
            self.app.update()

            self.assertLess(abs(browser._toggle_group.winfo_rooty() - browser._actions_left.winfo_rooty()), 12)
            self.assertTrue(browser._toggle_separator.winfo_ismapped())

    def test_the_layout_of_the_buttons_follows_the_font(self):
        with patch.object(tk.Misc, "winfo_screenwidth", return_value=1500):
            browser = self.open()
            browser.set_font_size(8)
            self.app.update()
            one_row = browser._toggle_separator.winfo_ismapped()

            browser.set_font_size(20)
            self.app.update()

            self.assertTrue(one_row)
            self.assertFalse(browser._toggle_separator.winfo_ismapped())  # too wide for one row at the large size


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


class SetFilterAndSortTest(BrowserTestCase):
    OUTAGE_PLAYERS = [
        player("Aktivni 1", False, reported=ago(hours=1)),
        player("Aktivni 2", False, reported=ago(minutes=5)),
        player("Aktivni 3", True, reported=ago(minutes=1)),  # online: must not show up
        player("Jina pobocka", False, reported=ago(minutes=2)),  # offline but not "aktivni": must not show up
    ]

    def test_sets_the_name_and_status_filters_and_the_sort_and_applies_them(self):
        browser = self.open(players=self.OUTAGE_PLAYERS)

        browser.set_filter_and_sort(name="aktivni", online=False, sort_column="reported", sort_descending=True)

        self.assertEqual(browser.name_var.get(), "aktivni")
        self.assertEqual(browser.status_box.get(), "Offline")
        self.assertEqual(browser.visible_names(), ["Aktivni 2", "Aktivni 1"])

    def test_applying_it_again_overrides_whatever_was_chosen_by_hand(self):
        browser = self.open(players=self.OUTAGE_PLAYERS)
        browser.name_var.set("jina")
        self.choose(browser.status_box, "Online")

        browser.set_filter_and_sort(name="aktivni", online=False, sort_column="reported", sort_descending=True)

        self.assertEqual(browser.visible_names(), ["Aktivni 2", "Aktivni 1"])

    def test_a_filter_left_over_from_before_does_not_hide_the_players_looked_for(self):
        players = self.OUTAGE_PLAYERS + [player("Aktivni 5", False, group="Obchod", reported=ago(minutes=9),
                                                notes="rozbitá", version="5.3.1"),
                                         player("Lobby", True, group="Kancelar", reported=ago(seconds=20))]
        browser = self.open(players=players)
        self.tick(browser, browser.group_box, "Kancelar")  # nobody of the outage is in this group
        self.type_into(browser, browser.note_var, "nic takového")
        self.choose(browser.reported_box, "< 1 minuta")
        self.assertEqual(browser.visible_names(), [])

        browser.set_filter_and_sort(name="aktivni", online=False, sort_column="reported", sort_descending=True)

        self.assertEqual(browser.visible_names(), ["Aktivni 2", "Aktivni 5", "Aktivni 1"])
        self.assertEqual((browser.note_var.get(), browser.reported_box.get()), ("", "(vše)"))
        self.assertEqual(browser.group_box.checked(), frozenset())

    def test_a_player_that_never_reported_comes_last_not_first_in_the_newest_first_order(self):
        players = self.OUTAGE_PLAYERS + [player("Aktivni 4", False, reported=0)]  # never reported
        browser = self.open(players=players)

        browser.set_filter_and_sort(name="aktivni", online=False, sort_column="reported", sort_descending=True)

        self.assertEqual(browser.visible_names(), ["Aktivni 2", "Aktivni 1", "Aktivni 4"])

    def test_the_sort_column_is_shown_when_it_was_hidden_so_that_the_sort_can_be_seen(self):
        saved = []
        browser = self.open(players=self.OUTAGE_PLAYERS, hidden_columns=["reported", "note"],
                            save_hidden_columns=saved.append)
        self.assertIn("reported", browser._hidden)

        browser.set_filter_and_sort(name="aktivni", online=False, sort_column="reported", sort_descending=True)

        self.assertNotIn("reported", browser._hidden)
        self.assertEqual(browser._sort, ("reported", True))
        self.assertIn("▼", browser._header_cells["reported"].cget("text"))
        self.assertTrue(browser._header_cells["reported"].winfo_ismapped())
        self.assertNotIn("reported", saved[-1])  # the choice of columns is remembered like any other change of it
        self.assertEqual(browser.visible_names(), ["Aktivni 2", "Aktivni 1"])

    def test_a_column_that_is_shown_already_is_left_alone(self):
        saved = []
        browser = self.open(players=self.OUTAGE_PLAYERS, save_hidden_columns=saved.append)

        browser.set_filter_and_sort(name="aktivni", online=False, sort_column="reported", sort_descending=True)

        self.assertEqual(saved, [])


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
        cells = [w.cget("text") for w in browser.widgets_for(row)[1:]]
        self.assertEqual((cells[1], cells[7]), ("Online", "opraveno"))
        self.assertEqual(len(browser._rows), 4)  # the old rows are gone, not piled up
        self.assertEqual(sum(r is not None for r in browser._pool_rows), 4)  # and shown, not stale ones
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


def paging_server(players, ignore_page=False, default_page_size=None):
    """
    A ServerApi over a fake server that behaves like the real one, as measured on a demo account: /players
    numbers its pages from 0, honours per_page, and its "pages" field is 1 for any page that has players (0 for
    an empty one) whatever the real number of pages is. Asked for no page size it answers everything, unless
    `default_page_size` says that its default page is smaller than the account: the demo account is too small
    to show whether that happens, and code that relies on the default would then silently lose players.
    """
    server = ServerApi.__new__(ServerApi)
    calls = []

    def make_request(method, endpoint, params=None, **kwargs):
        calls.append(dict(params or {}))
        assert (method, endpoint) == ("get", "/players"), (method, endpoint)
        params = params or {}
        per_page = params.get("per_page", default_page_size or len(players) or 1)
        page = 0 if ignore_page else params.get("page", 0)
        chunk = players[page * per_page:(page + 1) * per_page]
        return {"success": True, "data": {"objects": chunk, "page": page, "pages": 1 if chunk else 0,
                                          "count": len(chunk)}}

    server._make_request = MagicMock(side_effect=make_request)
    server.calls = calls
    return server


def fake_players(count):
    return [{"_id": f"id{i}", "name": f"P{i}", "group": {"_id": f"g{i}", "name": f"Group{i}"},
             "configLocation": f"Loc{i}", "notes": f"note{i}", "labels": [f"Label{i}"], "playlists": [f"PL{i}"],
             "version": f"1.{i}", "isConnected": True, "playlistOn": True, "tvStatus": True}
            for i in range(count)]


class ServerPlayersTest(unittest.TestCase):
    def test_all_pages_are_fetched_whatever_the_server_says_about_the_number_of_pages(self):
        players = fake_players(1203)
        server = paging_server(players, default_page_size=500)

        self.assertEqual(server.get_player_objects(), players)

    def test_pages_are_numbered_from_zero_with_an_explicit_size_and_end_with_an_empty_one(self):
        with patch("api_testing.request_calls.PLAYERS_PER_PAGE", 4):
            server = paging_server(fake_players(10))

            server.get_player_objects()

        self.assertEqual(server.calls, [{"page": 0, "per_page": 4}, {"page": 1, "per_page": 4},
                                        {"page": 2, "per_page": 4}, {"page": 3, "per_page": 4}])

    def test_a_server_that_ignores_the_page_number_does_not_loop_forever_or_duplicate_players(self):
        players = fake_players(5)
        server = paging_server(players, ignore_page=True)

        self.assertEqual(server.get_player_objects(), players)
        self.assertEqual(len(server.calls), 2)

    def test_players_without_an_id_are_told_apart_by_their_content(self):
        players = [{"name": "a"}, {"name": "b"}]
        server = paging_server(players)

        self.assertEqual(server.get_player_objects(), players)

    def test_an_account_without_players_gives_an_empty_list(self):
        self.assertEqual(paging_server([]).get_player_objects(), [])

    def test_a_small_account_costs_one_request_and_one_empty_page(self):
        server = paging_server(fake_players(3))

        server.get_player_objects()

        self.assertEqual(len(server.calls), 2)


class EveryReaderOfPlayersSeesAllPagesTest(unittest.TestCase):
    """The player on the last page was invisible to all but two readers: now none of them stops at the first page."""

    def setUp(self):
        patcher = patch("api_testing.request_calls.PLAYERS_PER_PAGE", 4)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.players = fake_players(10)  # P9 is alone on the third page
        self.server = paging_server(self.players, default_page_size=4)

    def test_the_lists_of_names_and_ids_include_the_player_on_the_last_page(self):
        self.assertIn("P9", self.server.get_player_names())
        self.assertEqual(self.server.get_player_id_by_name("P9"), "id9")
        self.assertIn("P9", [p["name"] for p in self.server.get_players_for_deploy()])

    def test_a_player_that_does_not_exist_is_reported_as_such(self):
        from api_testing.request_calls import NameResolutionError

        with self.assertRaises(NameResolutionError):
            self.server.get_player_id_by_name("Nobody")

    def test_deploy_to_selected_groups_includes_a_player_of_the_last_page(self):
        self.assertEqual([p["name"] for p in self.server.get_players_for_deploy(["Group9"])], ["P9"])

    def test_every_player_attribute_reader_includes_the_last_page(self):
        readers = {
            "get_player_locations": lambda rows: ("P9", "Loc9") in rows,
            "get_player_notes": lambda rows: ("P9", "note9") in rows,
            "get_player_labels": lambda rows: ("P9", ["Label9"]) in rows,
            "get_additional_playlists": lambda rows: ("P9", ["PL9"]) in rows,
            "get_versions": lambda rows: ("P9", "1.9") in rows,
            "get_players_groups": lambda rows: ("P9", "Group9") in rows,
            "get_players_details": lambda rows: any(row[0] == "P9" for row in rows),
            "get_player_details_overview": lambda rows: any(row["name"] == "P9" for row in rows),
            "get_all_players": lambda rows: "P9" in rows,
            "get_online_players": lambda rows: "P9" in rows,
        }
        for name, includes_last in readers.items():
            with self.subTest(reader=name):
                self.assertTrue(includes_last(getattr(self.server, name)()))

    def test_a_group_used_only_by_a_player_of_the_last_page_is_not_unused(self):
        self.server.get_group_names = MagicMock(return_value=["Group0", "Group9", "Nobody's"])

        self.assertEqual(self.server.get_unused_groups(), ["Nobody's"])

    def test_a_location_and_a_label_used_only_on_the_last_page_are_not_unused(self):
        self.server.get_locations = MagicMock(return_value=[{"Loc9": []}, {"Free": []}])
        self.server.get_labels = MagicMock(return_value=["Label9", "Free"])
        self.server.get_group_labels = MagicMock(return_value=[])
        self.server.get_assets_labels = MagicMock(return_value=[])
        responses = {"/playlists": {"data": []}, "/locations": {"data": []}}
        original = self.server._make_request.side_effect
        self.server._make_request.side_effect = (
            lambda method, endpoint, **kwargs: responses[endpoint] if endpoint in responses
            else original(method, endpoint, **kwargs))

        self.assertEqual(self.server.get_unused_locations(), ["Free"])
        self.assertEqual(self.server.get_unused_labels(), ["Free"])

    def test_a_player_without_a_group_does_not_break_the_readers(self):
        players = [{"_id": "a", "name": "NoGroup", "group": None, "piTemperature": None}]
        server = paging_server(players)

        self.assertEqual(server.get_players_groups(), [("NoGroup", "")])
        self.assertEqual(server.get_player_details_overview()[0]["group"], "")
        self.assertEqual(server.get_player_details_overview()[0]["temperature"], "")


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
            first.is_for.side_effect = lambda url, login, password: (url, login) == ("https://x", "jane")
            self.app.perform_show_action(ACTION, "https://x", "jane", "pw", None)
            self.app.perform_show_action(ACTION, "https://x", "jane", "pw", None)

            browser_class.assert_called_once()
            first.lift.assert_called_once()

    def test_another_login_replaces_the_window(self):
        with patch("gui_app.gui.PlayerBrowser") as browser_class:
            first = browser_class.return_value
            first.winfo_exists.return_value = True
            first.connection = ("https://x", "jane")
            first.is_for.side_effect = lambda url, login, password: (url, login) == ("https://x", "jane")
            self.app.perform_show_action(ACTION, "https://x", "jane", "pw", None)
            self.app.perform_show_action(ACTION, "https://y", "john", "pw", None)

            first.destroy.assert_called_once()
            self.assertEqual(browser_class.call_count, 2)

    def test_the_same_login_with_another_password_gets_a_window_of_its_own(self):
        with patch("gui_app.gui.PlayerBrowser") as browser_class:
            first = browser_class.return_value
            first.winfo_exists.return_value = True
            first.connection = ("https://x", "jane")
            first.is_for.side_effect = lambda url, login, password: (url, login, password) == ("https://x", "jane", "bad")
            self.app.open_player_browser("https://x", "jane", "bad")
            self.app.open_player_browser("https://x", "jane", "good")  # the old window shows an error with the old one

            first.destroy.assert_called_once()
            self.assertEqual(browser_class.call_count, 2)

    def test_removing_a_login_or_an_account_closes_its_player_window_and_only_that(self):
        self.app.all_data["logins"]["Demo"] = {"url": "https://x", "names": {"jane": {"login": "jane"},
                                                                            "john": {"login": "john"}}}
        self.app.all_data["logins"]["Other"] = {"url": "https://y", "names": {"jane": {"login": "jane"}}}
        self.app.account_data = self.app.all_data["logins"]
        self.app.save_account_configs()
        for removal, account, login, closes in (("remove_login", "Demo", "jane", True),
                                                ("remove_login", "Demo", "john", False),
                                                ("remove_login", "Other", "jane", False),
                                                ("remove_account", "Demo", "jane", True),
                                                ("remove_account", "Other", "jane", False)):
            with self.subTest(removal=removal, account=account, login=login):
                with patch.object(gui.messagebox, "askyesno", return_value=True), patch.object(gui.messagebox, "showwarning"):
                    self.app.all_data["logins"]["Demo"] = {"url": "https://x", "names": {
                        "jane": {"login": "jane"}, "john": {"login": "john"}}}
                    self.app.all_data["logins"]["Other"] = {"url": "https://y", "names": {"jane": {"login": "jane"}}}
                    self.app.account_data = self.app.all_data["logins"]
                    self.app.save_account_configs()
                    window = MagicMock()
                    window.winfo_exists.return_value = True
                    window.connection = ("https://x", "jane")
                    self.app._player_browser = window
                    self.app.option_choose_administration.set(account)
                    self.app.fill_login_details()
                    self.app.option_choose_name.set(login)

                    getattr(self.app, removal)()

                    self.assertEqual(window.destroy.called, closes)

    def test_on_open_is_called_whether_the_window_is_created_or_reused(self):
        with patch("gui_app.gui.PlayerBrowser") as browser_class:
            first = browser_class.return_value
            first.winfo_exists.return_value = True
            first.connection = ("https://x", "jane")
            first.is_for.side_effect = lambda url, login, password: (url, login) == ("https://x", "jane")
            on_open = MagicMock()
            self.app.open_player_browser("https://x", "jane", "pw", on_open=on_open)
            self.app.open_player_browser("https://x", "jane", "pw", on_open=on_open)

            self.assertEqual(on_open.call_args_list, [call(first), call(first)])

    def test_a_window_that_was_open_is_refreshed_on_request_a_new_one_is_not(self):
        with patch("gui_app.gui.PlayerBrowser") as browser_class:
            window = browser_class.return_value
            window.winfo_exists.return_value = True
            window.connection = ("https://x", "jane")
            window.is_for.side_effect = lambda url, login, password: (url, login) == ("https://x", "jane")

            self.app.open_player_browser("https://x", "jane", "pw", refresh_if_open=True)  # it is created: loads anyway
            window.refresh.assert_not_called()
            self.app.open_player_browser("https://x", "jane", "pw", refresh_if_open=True)  # already open: old data
            window.refresh.assert_called_once()
            self.app.open_player_browser("https://x", "jane", "pw")  # Live-view only brings it to the front
            window.refresh.assert_called_once()

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
            # saved before the temperature and the version existed: they are off, as they are by default
            self.assertEqual(options["hidden_columns"], ["note", "temperature", "version"])

            options["save_hidden_columns"](["group", "note", "temperature"])  # the version was switched on

        with open(self.app.config_file, encoding="utf-8") as file:
            saved = json.load(file)["logins"]
        self.assertEqual(saved["Demo"]["player_hidden"], ["group", "note"])
        self.assertEqual(saved["Demo"]["player_shown"], ["version"])
        self.assertNotIn("player_hidden", saved["Other"])
        options["save_hidden_columns"](["temperature", "version"])  # back to the defaults
        with open(self.app.config_file, encoding="utf-8") as file:
            entry = json.load(file)["logins"]["Demo"]
        self.assertNotIn("player_hidden", entry)
        self.assertNotIn("player_shown", entry)

    def test_an_account_that_never_chose_has_the_temperature_and_the_version_off(self):
        self.app.all_data["logins"]["Demo"] = {"url": "https://x", "names": {}}
        self.app.account_data = self.app.all_data["logins"]
        self.app.save_account_configs()
        self.app.option_choose_administration.set("Demo")
        with patch("gui_app.gui.PlayerBrowser") as browser_class:
            self.app.open_player_browser("https://x", "jane", "pw")

        self.assertEqual(browser_class.call_args.kwargs["hidden_columns"], ["temperature", "version"])

    def test_the_hidden_columns_and_the_widths_are_stored_side_by_side(self):
        self.app.all_data["logins"]["Demo"] = {"url": "https://x", "names": {}}
        self.app.account_data = self.app.all_data["logins"]
        self.app.save_account_configs()

        self.app.save_player_columns("Demo", {"name": 300})
        self.app.save_hidden_player_columns("Demo", ["label", "temperature", "version"])
        self.app.save_player_columns("Demo", {})

        with open(self.app.config_file, encoding="utf-8") as file:
            entry = json.load(file)["logins"]["Demo"]
        self.assertEqual(entry["player_hidden"], ["label"])
        self.assertNotIn("player_columns", entry)

    def test_saving_hidden_columns_for_a_removed_account_writes_nothing(self):
        self.app.save_hidden_player_columns("Gone", ["note"])

        with open(self.app.config_file, encoding="utf-8") as file:
            self.assertEqual(json.load(file)["logins"], {})

    def test_the_size_of_the_snapshot_windows_is_stored_per_account(self):
        self.app.all_data["logins"]["Demo"] = {"url": "https://x", "names": {}}
        self.app.account_data = self.app.all_data["logins"]
        self.app.save_account_configs()

        self.app.save_snapshot_window_size("Demo", (1100, 700))

        with open(self.app.config_file, encoding="utf-8") as file:
            self.assertEqual(json.load(file)["logins"]["Demo"]["snapshot_window"], [1100, 700])

    def test_the_stored_size_of_the_snapshot_windows_is_given_to_the_browser(self):
        self.app.all_data["logins"]["Demo"] = {"url": "https://x", "names": {}, "snapshot_window": [1100, 700]}
        self.app.account_data = self.app.all_data["logins"]
        self.app.save_account_configs()
        self.app.option_choose_administration.set("Demo")
        with patch("gui_app.gui.PlayerBrowser") as browser_class:
            self.app.open_player_browser("https://x", "jane", "pw")

        self.assertEqual(browser_class.call_args.kwargs["snapshot_size"], [1100, 700])
        browser_class.call_args.kwargs["save_snapshot_size"]((900, 600))
        with open(self.app.config_file, encoding="utf-8") as file:
            self.assertEqual(json.load(file)["logins"]["Demo"]["snapshot_window"], [900, 600])

    def test_saving_the_snapshot_window_size_for_a_removed_account_writes_nothing(self):
        self.app.save_snapshot_window_size("Gone", (1100, 700))

        with open(self.app.config_file, encoding="utf-8") as file:
            self.assertEqual(json.load(file)["logins"], {})

    def test_the_place_of_the_table_window_is_stored_per_account_and_given_to_the_browser(self):
        self.app.all_data["logins"]["Demo"] = {"url": "https://x", "names": {}, "player_window": [1150, 640, 120, 130]}
        self.app.account_data = self.app.all_data["logins"]
        self.app.save_account_configs()
        self.app.option_choose_administration.set("Demo")
        with patch("gui_app.gui.PlayerBrowser") as browser_class:
            self.app.open_player_browser("https://x", "jane", "pw")

        self.assertEqual(browser_class.call_args.kwargs["window_geometry"], [1150, 640, 120, 130])
        browser_class.call_args.kwargs["save_window_geometry"]((1000, 650, 150, 110))
        with open(self.app.config_file, encoding="utf-8") as file:
            self.assertEqual(json.load(file)["logins"]["Demo"]["player_window"], [1000, 650, 150, 110])

    def test_saving_the_table_window_place_for_a_removed_account_writes_nothing(self):
        self.app.save_player_window_geometry("Gone", (1000, 650, 150, 110))

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


class TableButtons:
    """Finding, pressing and looking at the snapshot buttons of the table."""

    @staticmethod
    def button(browser, name):
        row = next(row for row in browser._rows if row.name == name)
        return row, browser.widgets_for(row)[0]

    @staticmethod
    def press(button):
        press(button)

    @staticmethod
    def fill(button):
        return fill(button)


class SnapshotButtonTest(TableButtons, BrowserTestCase):
    def open_with_snapshots(self, players=PLAYERS, **options):
        self.snapshot_fetch = MagicMock(return_value=(b"\x89PNG\r\n\x1a\n", ".png"))
        return self.open(players=players, snapshot_fetch=self.snapshot_fetch, **options)

    def test_the_button_is_pressable_for_an_online_player_only(self):
        browser = self.open_with_snapshots()

        self.assertTrue(button_interactive(self.button(browser, "Lobby")[1]))
        self.assertTrue(button_interactive(self.button(browser, "Sklad")[1]))
        self.assertFalse(button_interactive(self.button(browser, "Prerov 1")[1]))

    def test_the_button_is_green_where_a_snapshot_can_be_asked_for_and_red_where_not(self):
        browser = self.open_with_snapshots()

        self.assertEqual(self.fill(self.button(browser, "Lobby")[1]), GREEN.normal)
        self.assertEqual(self.fill(self.button(browser, "Sklad")[1]), GREEN.normal)
        self.assertEqual(self.fill(self.button(browser, "Prerov 1")[1]), RED.normal)

    def test_a_red_button_does_nothing_when_pressed_or_hovered(self):
        browser = self.open_with_snapshots()
        button = self.button(browser, "Prerov 1")[1]

        button.event_generate("<Enter>")
        self.assertEqual(self.fill(button), RED.normal)
        self.press(button)
        self.app.update()

        self.assertEqual(browser._viewers, {})
        self.snapshot_fetch.assert_not_called()

    def test_the_colours_stay_after_a_refresh_and_a_change_of_the_text_size(self):
        browser = self.open_with_snapshots()

        self.clock[0] += 20
        browser.refresh()
        self.wait_for(lambda: not browser._loading)
        browser.set_font_size(16)

        self.assertEqual(self.fill(self.button(browser, "Lobby")[1]), GREEN.normal)
        self.assertEqual(self.fill(self.button(browser, "Prerov 1")[1]), RED.normal)
        self.assertEqual(font_of(self.button(browser, "Lobby")[1])[1], 16)

    def test_a_player_without_an_id_cannot_be_asked(self):
        rows = [{**player("Bez id"), "_id": ""}]
        browser = self.open_with_snapshots(players=rows)

        self.assertFalse(button_interactive(self.button(browser, "Bez id")[1]))

    def test_pressing_the_button_opens_the_window_of_that_player(self):
        browser = self.open_with_snapshots()
        row, button = self.button(browser, "Lobby")

        self.press(button)
        viewer = browser._viewers["id-Lobby"]
        self.wait_for(lambda: not viewer.busy)

        self.assertEqual(viewer.title(), "Snímek - Lobby")
        self.snapshot_fetch.assert_called_once_with("https://demo.example.com", "jane", "pw", "id-Lobby")

    def test_a_second_press_brings_the_same_window_forward(self):
        browser = self.open_with_snapshots()
        row, button = self.button(browser, "Lobby")
        self.press(button)
        viewer = browser._viewers["id-Lobby"]
        self.wait_for(lambda: not viewer.busy)

        self.press(button)
        self.app.update()

        self.assertIs(browser._viewers["id-Lobby"], viewer)
        self.assertEqual(len(browser._viewers), 1)

    def test_every_player_has_a_window_of_its_own(self):
        browser = self.open_with_snapshots()
        for name in ("Lobby", "Sklad"):
            self.press(self.button(browser, name)[1])

        self.assertEqual(sorted(browser._viewers), ["id-Lobby", "id-Sklad"])

    def test_the_sixth_window_is_refused_with_a_message_until_one_is_closed(self):
        players = [player(f"P{index}") for index in range(7)]
        browser = self.open_with_snapshots(players=players)
        with patch("gui_app.player_browser.messagebox.showinfo") as info:
            for index in range(5):
                self.press(self.button(browser, f"P{index}")[1])
            info.assert_not_called()

            self.press(self.button(browser, "P5")[1])

            self.assertEqual(len(browser._viewers), 5)
            self.assertNotIn("id-P5", browser._viewers)
            self.assertIn("5 náhledů", info.call_args.args[1])

            browser._viewers["id-P0"].destroy()
            self.assertEqual(len(browser._viewers), 4)
            info.reset_mock()
            self.press(self.button(browser, "P5")[1])

            info.assert_not_called()
            self.assertIn("id-P5", browser._viewers)

    def test_pressing_the_button_of_an_open_window_is_allowed_at_the_limit(self):
        players = [player(f"P{index}") for index in range(6)]
        browser = self.open_with_snapshots(players=players)
        with patch("gui_app.player_browser.messagebox.showinfo") as info:
            for index in range(5):
                self.press(self.button(browser, f"P{index}")[1])
            self.press(self.button(browser, "P2")[1])

            info.assert_not_called()

    def test_a_window_stays_when_the_players_are_refreshed(self):
        browser = self.open_with_snapshots()
        self.press(self.button(browser, "Lobby")[1])
        viewer = browser._viewers["id-Lobby"]

        self.clock[0] += 20
        browser.refresh()
        self.wait_for(lambda: not browser._loading)
        self.press(self.button(browser, "Lobby")[1])

        self.assertIs(browser._viewers["id-Lobby"], viewer)
        self.assertTrue(viewer.winfo_exists())

    def test_the_next_window_opens_in_the_size_the_user_gave_the_previous_one(self):
        saved = MagicMock()
        browser = self.open_with_snapshots(save_snapshot_size=saved)
        self.press(self.button(browser, "Lobby")[1])
        self.app.update()
        first = browser._viewers["id-Lobby"]
        self.wait_for(lambda: not first.busy)

        with patch("gui_app.snapshot_viewer.RESIZE_REPORT_DELAY_MS", 400):
            first.geometry("1100x700")
            self.wait_for(lambda: saved.called)
        self.press(self.button(browser, "Sklad")[1])
        self.app.update()
        second = browser._viewers["id-Sklad"]

        saved.assert_called_once_with((1100, 700))
        self.assertEqual((second.winfo_width(), second.winfo_height()), (1100, 700))

    def test_the_size_that_was_saved_before_is_used_from_the_start(self):
        browser = self.open_with_snapshots(snapshot_size=[1000, 650])
        self.press(self.button(browser, "Lobby")[1])
        self.app.update()
        viewer = browser._viewers["id-Lobby"]

        self.assertEqual((viewer.winfo_width(), viewer.winfo_height()), (1000, 650))

    def test_a_damaged_saved_size_is_ignored(self):
        browser = self.open_with_snapshots(snapshot_size=[5, "x"])
        self.press(self.button(browser, "Lobby")[1])
        self.app.update()
        viewer = browser._viewers["id-Lobby"]

        self.assertEqual((viewer.winfo_width(), viewer.winfo_height()), DEFAULT_WINDOW_SIZE)

    def test_opening_and_closing_windows_saves_nothing_while_the_user_changes_no_size(self):
        saved = MagicMock()
        browser = self.open_with_snapshots(save_snapshot_size=saved)
        self.press(self.button(browser, "Lobby")[1])
        self.app.update()
        self.press(self.button(browser, "Sklad")[1])
        self.app.update()
        for viewer in list(browser._viewers.values()):
            viewer.destroy()
        self.app.update()

        saved.assert_not_called()

    def test_the_same_size_is_not_saved_again(self):
        saved = MagicMock()
        browser = self.open_with_snapshots(save_snapshot_size=saved)
        self.press(self.button(browser, "Lobby")[1])
        self.app.update()
        viewer = browser._viewers["id-Lobby"]
        with patch("gui_app.snapshot_viewer.RESIZE_REPORT_DELAY_MS", 400):
            viewer.geometry("1100x700")
            self.wait_for(lambda: saved.called)
            viewer.geometry("1000x650")
            viewer.geometry("1100x700")
            self.app.update()
            self.wait_for(lambda: viewer._report_id is None)

        saved.assert_called_once_with((1100, 700))

    def test_the_windows_are_shifted_so_that_none_hides_another(self):
        browser = self.open_with_snapshots()
        self.press(self.button(browser, "Lobby")[1])
        self.app.update()
        self.press(self.button(browser, "Sklad")[1])
        self.app.update()
        first, second = browser._viewers["id-Lobby"], browser._viewers["id-Sklad"]

        self.assertEqual((second.winfo_x() - first.winfo_x(), second.winfo_y() - first.winfo_y()), (30, 30))

    def test_the_text_size_follows_to_the_open_windows(self):
        browser = self.open_with_snapshots()
        self.press(self.button(browser, "Lobby")[1])

        browser.set_font_size(16)

        self.assertEqual(browser._viewers["id-Lobby"]._font[1], 16)

    def test_the_slots_are_shared_by_the_windows_of_the_account(self):
        browser = self.open_with_snapshots()
        self.press(self.button(browser, "Lobby")[1])
        self.press(self.button(browser, "Sklad")[1])

        self.assertIs(browser._viewers["id-Lobby"]._slots, browser._viewers["id-Sklad"]._slots)
        self.assertEqual(browser._snapshot_slots.limit, 3)


class AutoRefreshTest(TableButtons, BrowserTestCase):
    """A window left open updates itself (the interval is made short here, and the refresh interval is skipped)."""

    def setUp(self):
        super().setUp()
        for name, value in (("AUTO_REFRESH_SECONDS", 0.25), ("AUTO_REFRESH_RETRY_MS", 100)):
            patcher = patch(f"gui_app.player_browser.{name}", value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def open_auto(self, fetch, **options):
        browser = self.open(fetch=fetch, snapshot_fetch=MagicMock(), **options)
        self.clock[0] += 1000  # the ten seconds between two downloads are over
        return browser

    def test_the_window_updates_itself_after_the_interval(self):
        fetch = MagicMock(return_value=PLAYERS)
        browser = self.open_auto(fetch)

        self.wait_for(lambda: fetch.call_count == 2 and not browser._loading)
        self.clock[0] += 1000
        self.wait_for(lambda: fetch.call_count == 3 and not browser._loading)

    def test_the_interval_starts_again_with_every_update(self):
        fetch = MagicMock(return_value=PLAYERS)
        browser = self.open_auto(fetch)
        before = browser._auto_after_id

        browser.refresh()
        self.wait_for(lambda: not browser._loading)

        self.assertIsNotNone(browser._auto_after_id)
        self.assertNotEqual(browser._auto_after_id, before)

    def test_a_player_that_went_offline_gets_a_red_button(self):
        changed = make_players()
        changed[0]["isConnected"] = False  # Lobby
        fetch = MagicMock(side_effect=[PLAYERS, changed, changed, changed, changed])
        browser = self.open_auto(fetch)
        self.assertEqual(self.fill(self.button(browser, "Lobby")[1]), GREEN.normal)

        self.wait_for(lambda: fetch.call_count >= 2 and not browser._loading)

        button = self.button(browser, "Lobby")[1]
        self.assertEqual(self.fill(button), RED.normal)
        self.assertFalse(button_interactive(button))
        self.assertEqual(self.button(browser, "Sklad")[1].cget("text"), "Snímek")

    def test_a_player_that_came_online_gets_a_green_button(self):
        changed = make_players()
        changed[1]["isConnected"] = True  # Prerov 1
        fetch = MagicMock(side_effect=[PLAYERS, changed, changed, changed, changed])
        browser = self.open_auto(fetch)
        self.assertEqual(self.fill(self.button(browser, "Prerov 1")[1]), RED.normal)

        self.wait_for(lambda: fetch.call_count >= 2 and not browser._loading)

        self.assertEqual(self.fill(self.button(browser, "Prerov 1")[1]), GREEN.normal)
        self.assertTrue(button_interactive(self.button(browser, "Prerov 1")[1]))

    def test_a_failed_automatic_update_keeps_the_table_and_says_so(self):
        fetch = MagicMock(side_effect=[PLAYERS] + [requests.exceptions.ConnectionError()] * 5)
        browser = self.open_auto(fetch)

        self.wait_for(lambda: fetch.call_count >= 2 and not browser._loading)

        self.assertEqual(len(browser._rows), 4)
        self.assertIn("nepodařilo načíst", browser.status_var.get())

    def test_the_table_stays_scrolled_where_it_was(self):
        many = [player(f"P{index:02d}") for index in range(60)]
        fetch = MagicMock(return_value=many)
        browser = self.open(fetch=fetch, snapshot_fetch=MagicMock())
        browser.geometry("1000x400")
        self.app.update()
        browser._scroll_y("moveto", 0.5)
        self.app.update()
        before = browser._first_index
        self.assertGreater(before, 0)

        self.clock[0] += 1000
        browser.refresh()
        self.wait_for(lambda: not browser._loading)
        self.app.update()

        self.assertEqual(browser._first_index, before)

    def test_a_filter_change_still_goes_back_to_the_top(self):
        many = [player(f"P{index:02d}") for index in range(60)]
        browser = self.open(fetch=MagicMock(return_value=many), snapshot_fetch=MagicMock())
        browser.geometry("1000x400")
        self.app.update()
        browser._scroll_y("moveto", 0.5)
        self.app.update()

        browser.name_var.set("P")
        self.wait_for(lambda: len(browser.visible_names()) == 60 and browser._first_index == 0)

    def test_it_waits_while_a_list_of_choices_is_open(self):
        fetch = MagicMock(return_value=PLAYERS)
        browser = self.open(fetch=fetch, snapshot_fetch=MagicMock())
        browser.group_box.open()
        self.clock[0] += 1000

        end = time.monotonic() + 0.8
        while time.monotonic() < end:
            self.app.update()
            time.sleep(0.01)
        self.assertEqual(fetch.call_count, 1)

        browser.group_box.close()
        self.wait_for(lambda: fetch.call_count == 2)

    def test_a_closed_window_updates_no_more(self):
        fetch = MagicMock(return_value=PLAYERS)
        browser = self.open_auto(fetch)

        browser.destroy()
        count = fetch.call_count
        end = time.monotonic() + 0.6
        while time.monotonic() < end:
            self.app.update()
            time.sleep(0.01)

        self.assertEqual(fetch.call_count, count)


class WindowGeometryTest(BrowserTestCase):
    """The table window opens where and how large the user left it, and says when they move or resize it."""

    def setUp(self):
        super().setUp()
        # Comfortably above what a real geometry() + update() cycle costs under the test suite (measured up to ~50 ms):
        # too close to that and three rapid moves in a row (see test_moving_and_resizing_is_reported_once...)
        # can each have their delay elapse before the next one arrives, reporting every one, not only the last.
        patcher = patch("gui_app.player_browser.GEOMETRY_REPORT_DELAY_MS", 400)
        patcher.start()
        self.addCleanup(patcher.stop)

    def pump(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.update()
            time.sleep(0.01)

    def test_a_window_with_nothing_saved_opens_as_before(self):
        browser = self.open()
        self.app.update()

        self.assertEqual(browser.winfo_height(), 600)

    def test_it_opens_where_and_how_large_it_was_left(self):
        browser = self.open(window_geometry=[1300, 640, 120, 130])
        self.pump(0.2)

        self.assertEqual(browser.geometry(), "1300x640+120+130")

    def test_a_saved_width_too_small_for_the_buttons_is_widened(self):
        browser = self.open(window_geometry=[300, 640, 120, 130])  # 300 is the least a saved window can be
        self.pump(0.2)

        self.assertGreater(browser.winfo_width(), 300)
        self.assertGreaterEqual(browser.winfo_width(), browser._actions_bar.winfo_reqwidth())

    def test_a_size_larger_than_the_screen_is_cut_down_to_it(self):
        browser = self.open(window_geometry=[9000, 9000, 0, 100])
        self.pump(0.2)

        self.assertLess(browser.winfo_width(), browser.winfo_screenwidth())
        self.assertLess(browser.winfo_height(), browser.winfo_screenheight())

    def test_a_damaged_saved_geometry_is_ignored(self):
        for raw in ("1300x640+1+1", [1300, 640], [1300, 640, "x", 3], [5, 640, 1, 1], [True, 640, 1, 1], {}):
            with self.subTest(raw=raw):
                self.assertIsNone(valid_window_geometry(raw))
        browser = self.open(window_geometry=[5, "x", 1])
        self.app.update()

        self.assertEqual(browser.winfo_height(), 600)

    def test_moving_and_resizing_is_reported_once_with_the_final_place(self):
        saved = MagicMock()
        browser = self.open(save_window_geometry=saved)
        self.pump(0.2)

        for geometry in ("1300x650+150+110", "1350x660+160+120", "1400x680+170+130"):  # the pointer keeps moving
            browser.geometry(geometry)
            self.app.update()
        self.wait_for(lambda: saved.called)
        self.pump(0.2)

        saved.assert_called_once_with((1400, 680, 170, 130))

    def test_moving_alone_is_reported_too(self):
        saved = MagicMock()
        browser = self.open(save_window_geometry=saved)
        self.pump(0.2)
        size = browser.geometry().split("+")[0]

        browser.geometry(f"{size}+210+140")
        self.wait_for(lambda: saved.called)

        self.assertEqual(saved.call_args.args[0][2:], (210, 140))

    def test_opening_reports_nothing(self):
        saved = MagicMock()
        self.open(window_geometry=[1300, 640, 120, 130], save_window_geometry=saved)
        self.pump(0.4)

        saved.assert_not_called()

    def test_the_same_place_is_not_saved_again(self):
        saved = MagicMock()
        browser = self.open(window_geometry=[1300, 640, 120, 130], save_window_geometry=saved)
        self.pump(0.2)

        browser.geometry("1300x650+150+110")
        self.wait_for(lambda: saved.called)
        browser.geometry("1300x640+120+130")
        self.wait_for(lambda: saved.call_count == 2)
        browser.geometry("1300x640+120+130")
        self.pump(0.3)

        self.assertEqual([call.args[0] for call in saved.call_args_list], [(1300, 650, 150, 110), (1300, 640, 120, 130)])

    def test_a_window_closed_right_after_being_moved_still_reports_it(self):
        saved = MagicMock()
        browser = self.open(save_window_geometry=saved)
        self.pump(0.2)
        browser.geometry("1300x650+150+110")
        self.app.update()

        browser.destroy()

        saved.assert_called_once_with((1300, 650, 150, 110))

    def test_a_change_of_the_text_size_does_not_lose_the_place(self):
        browser = self.open(window_geometry=[1300, 640, 120, 130])
        self.pump(0.2)

        browser.set_font_size(14)
        self.pump(0.2)

        self.assertEqual(browser.geometry().split("+", 1)[1], "120+130")


class LargeTableTest(BrowserTestCase):
    """
    A row of widgets for every single player, hidden or not, used to make hundreds of players slow to open, scroll,
    filter or resize, and thousands of them worse still: it is a fixed pool now (see the class docstring of
    PlayerBrowser), as many rows of widgets as fit the window, whatever the account has - the scroll position is
    which one of _visible the pool starts showing, not a real position of anything on the canvas.
    """

    def open_large(self, count=310):
        players = [player(f"Player {index:03d}", index % 3 != 0, f"Group {index % 9}", f"Praha {index % 40}",
                          ["a", "b"], notes="poznamka " * 3, temperature="47.2", version="5.3.1")
                   for index in range(count)]
        fetch = MagicMock(return_value=players)
        return self.open(fetch=fetch), fetch

    def state(self, browser):
        return browser._canvas.itemcget(browser._body_item, "state")

    def seconds(self, action):
        started = time.perf_counter()
        action()
        self.app.update()
        return time.perf_counter() - started

    def test_hiding_and_showing_columns_and_changing_the_text_size_download_nothing(self):
        browser, fetch = self.open_large(60)

        browser.toggle_column("note")
        browser.toggle_column("note")
        browser.set_font_size(15)
        browser.set_font_size(12)
        browser.reset_columns()
        self.app.update()

        self.assertEqual(fetch.call_count, 1)

    def test_a_column_is_shown_or_hidden_in_a_fraction_of_a_second(self):
        browser, _ = self.open_large()

        hide = self.seconds(lambda: browser.toggle_column("location"))
        show = self.seconds(lambda: browser.toggle_column("location"))

        self.assertLess(max(hide, show), 1.5, f"{hide:.1f} s to hide, {show:.1f} s to show")

    def test_the_text_size_changes_in_a_fraction_of_a_second(self):
        browser, _ = self.open_large()

        larger = self.seconds(lambda: browser.set_font_size(14))
        smaller = self.seconds(lambda: browser.set_font_size(12))

        self.assertLess(max(larger, smaller), 1.5, f"{larger:.1f} s larger, {smaller:.1f} s smaller")

    def test_the_pool_of_row_widgets_never_grows_with_the_number_of_players(self):
        """The whole point: a few dozen live widgets however many players the account has, not one row for each."""
        small, _ = self.open_large(20)
        small_pool = len(small._pool)

        huge, _ = self.open_large(4000)

        self.assertEqual(len(huge._pool), small_pool)
        self.assertLess(len(huge._pool), 200)  # comfortably a screenful, nowhere near one row per player

    def test_opening_scrolling_and_resizing_a_huge_account_stays_fast(self):
        browser, _ = self.open_large(4000)

        opening = self.seconds(lambda: None)  # open_large already measured the open itself; this is the baseline
        scroll_middle = self.seconds(lambda: browser._scroll_y("moveto", 0.5))
        scroll_end = self.seconds(lambda: browser._scroll_y("moveto", 1.0))
        resize = self.seconds(lambda: browser.geometry("1500x850"))

        for label, seconds in (("scroll to the middle", scroll_middle), ("scroll to the end", scroll_end),
                               ("resize", resize)):
            with self.subTest(action=label):
                self.assertLess(seconds, 1.5, f"{label} took {seconds:.1f} s")
        self.assertLess(opening, 0.1)

    def test_scrolling_shows_the_actual_players_at_that_position(self):
        browser, _ = self.open_large(500)

        browser._scroll_y("moveto", 1.0)

        shown = [row.name for row in browser._pool_rows if row is not None]
        self.assertEqual(shown[-1], "Player 499")
        self.assertEqual(browser.widgets_for(browser._visible[-1])[1].cget("text"), "Player 499")

    def test_the_rows_are_hidden_during_a_change_and_shown_after_it(self):
        browser, _ = self.open_large(20)
        during = []
        real = browser._apply_widths

        def watching():
            during.append(self.state(browser))
            real()
        browser._apply_widths = watching
        self.assertEqual(self.state(browser), "normal")

        browser.set_font_size(14)
        browser.toggle_column("note")

        self.assertTrue(during and all(state == "hidden" for state in during), during)
        self.assertEqual(self.state(browser), "normal")

    def test_the_rows_are_shown_again_when_a_change_fails(self):
        browser, _ = self.open_large(20)

        with patch("gui_app.player_browser.sort_rows", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                browser.apply_filters()

        self.assertEqual(self.state(browser), "normal")
        browser.apply_filters()
        self.assertEqual(len(browser.visible_names()), 20)

    def test_a_change_inside_a_change_shows_the_rows_only_at_the_end(self):
        browser, _ = self.open_large(20)

        with browser._frozen():
            with browser._frozen():
                self.assertEqual(self.state(browser), "hidden")
            self.assertEqual(self.state(browser), "hidden")
        self.assertEqual(self.state(browser), "normal")


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
