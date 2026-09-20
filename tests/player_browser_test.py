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
from gui_app.player_browser import COLUMNS, PlayerBrowser
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

    def open(self, fetch=None, players=PLAYERS):
        fetch = fetch or MagicMock(return_value=players)
        browser = PlayerBrowser(self.app, url="https://demo.example.com", login="jane", password="pw",
                                account_name="Demo", fetch=fetch)
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
