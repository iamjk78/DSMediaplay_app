"""
The actions that delete things for good: an empty keyword must not remove everything, a name must not match as a
substring of another, only what is really unused may be deleted as "unused", and the user is asked first.
"""
import json
import os
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from api_testing.request_calls import ServerApi, require_keyword, zone_references
from gui_app import gui
from gui_app.log_box import LoggingTextBox
from processor.input_processing import (
    FormatException, InternalException, RemoveAllUnusedPlaylistsProcessor, RemoveAssetsProcessor,
    RemovePlaylistsByListProcessor, RemovePlaylistsProcessor, RemoveUnusedAssetsProcessor,
    RemoveUnusedLabelsProcessor, RemoveUnusedPlaylistsProcessor,
)

MESSAGES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "messages.json")


def make_processor(processor_class, server):
    """A processor whose log messages are their own keys, so the tests can tell which one was written."""
    lang = MagicMock()
    lang.get_message.side_effect = lambda key, **kwargs: key
    logger = MagicMock()
    processor = processor_class(logger, url="http://example.com", login="user", password="pass", lang=lang)
    server.__enter__.return_value = server
    patcher = patch.object(processor, "_try_server_login", return_value=server)
    patcher.start()
    return processor, logger, patcher


class EmptyKeywordTest(unittest.TestCase):
    def setUp(self):
        self.server = MagicMock()
        self.server.get_group_names.return_value = ["group1"]
        self.server.get_playlist_names.return_value = ["playlist1"]

    def test_a_group_line_without_a_keyword_is_refused_instead_of_removing_every_playlist(self):
        for line in ("group1", "group1\t", "group1\t   "):
            with self.subTest(line=line):
                processor, logger, patcher = make_processor(RemovePlaylistsProcessor, self.server)
                self.addCleanup(patcher.stop)

                with self.assertRaises(FormatException):
                    processor.load(line)

                self.assertEqual(processor.data, {})  # nothing is left for run() to remove
                logger.error.assert_any_call("empty_keyword")

    def test_a_playlist_line_without_a_keyword_is_refused_instead_of_removing_every_asset(self):
        for line in ("playlist1\t", "playlist1\t  "):
            with self.subTest(line=line):
                processor, logger, patcher = make_processor(RemoveAssetsProcessor, self.server)
                self.addCleanup(patcher.stop)

                with self.assertRaises(FormatException):
                    processor.load(line)

                self.assertEqual(processor.data, {})
                logger.error.assert_any_call("empty_keyword")

    def test_a_good_line_next_to_a_bad_one_does_not_make_the_bad_one_run(self):
        processor, logger, patcher = make_processor(RemovePlaylistsProcessor, self.server)
        self.addCleanup(patcher.stop)

        with self.assertRaises(FormatException):
            processor.load("group1\tkeyword\ngroup1\t")

        self.server.remove_playlists_by_keyword_from_group.assert_not_called()

    def test_a_real_keyword_still_works(self):
        processor, _, patcher = make_processor(RemovePlaylistsProcessor, self.server)
        self.addCleanup(patcher.stop)
        self.server.remove_playlists_by_keyword_from_group.return_value = ["playlist1"]

        processor.load("group1\tkey")
        list(processor.run())

        self.server.remove_playlists_by_keyword_from_group.assert_called_once_with("group1", "key")

    def test_the_server_methods_refuse_an_empty_keyword_themselves_too(self):
        api = ServerApi.__new__(ServerApi)
        api.get_group_id_by_name = MagicMock()
        api.get_all_playlists_details = MagicMock()

        for keyword in ("", "  ", None):
            with self.subTest(keyword=keyword):
                with self.assertRaises(ValueError):
                    api.remove_playlists_by_keyword_from_group("group1", keyword)
                with self.assertRaises(ValueError):
                    api.remove_assets_by_keyword_from_playlist("playlist1", keyword)

        api.get_group_id_by_name.assert_not_called()
        api.get_all_playlists_details.assert_not_called()

    def test_require_keyword_returns_a_real_keyword_unchanged(self):
        self.assertEqual(require_keyword(" a "), " a ")


class RemovePlaylistsByNameTest(unittest.TestCase):
    PLAYLISTS = {
        "G1": [{"playlist_name": "Promo"}, {"playlist_name": "Promo2026"}, {"playlist_name": "2026"},
               {"playlist_name": "o"}],
        "G2": [{"playlist_name": "Promo2026"}, {"playlist_name": "Other"}],
    }

    def make_api(self):
        api = ServerApi.__new__(ServerApi)
        api.get_groups_playlists_details = MagicMock(return_value=self.PLAYLISTS)
        api.set_playlist_to_group_detailed = MagicMock()
        return api

    def test_a_name_matches_only_exactly_not_as_a_part_of_other_names(self):
        api = self.make_api()

        removed = api.remove_playlists_from_groups(["Promo2026"])

        self.assertEqual(removed, {"G1": ["Promo2026"], "G2": ["Promo2026"]})
        kept = {call.args[0]: [row[0] for row in call.args[1]]
                for call in api.set_playlist_to_group_detailed.call_args_list}
        self.assertEqual(kept, {"G1": ["Promo", "2026", "o"], "G2": ["Other"]})

    def test_a_single_name_instead_of_a_list_is_refused(self):
        api = self.make_api()

        with self.assertRaises(TypeError):
            api.remove_playlists_from_groups("Promo2026")

        api.set_playlist_to_group_detailed.assert_not_called()

    def test_the_processor_hands_the_server_a_list_of_one_name(self):
        processor, _, patcher = make_processor(RemovePlaylistsByListProcessor, MagicMock())
        self.addCleanup(patcher.stop)
        server = MagicMock()
        server.remove_playlists_from_groups.return_value = {}

        processor._remove_method(server, "Promo2026")

        server.remove_playlists_from_groups.assert_called_once_with(["Promo2026"])


class UnusedDetectionTest(unittest.TestCase):
    """What counts as "used": every place that refers to an asset, a playlist or a label."""

    def make_api(self, responses):
        api = ServerApi.__new__(ServerApi)
        api._make_request = MagicMock(side_effect=lambda method, endpoint, **kwargs: responses[endpoint])
        return api

    def test_zone_references_ignore_missing_and_odd_values(self):
        playlist = {"assets": [{"filename": "a", "side": "S", "bottom": None, "zone4": "", "zone5": 5},
                               {"filename": "b", "zone6": "Z"}]}

        self.assertEqual(zone_references(playlist), ["S", "Z"])
        self.assertEqual(zone_references({"assets": None}), [])
        self.assertEqual(zone_references({}), [])

    def test_an_asset_used_only_in_a_zone_or_as_a_logo_is_not_unused(self):
        api = self.make_api({
            "/files": {"data": {"dbdata": [{"name": "main.mp4"}, {"name": "zone.png"}, {"name": "logo.png"},
                                           {"name": "free.png"}]}},
            "/playlists": {"data": [{"name": "P", "assets": [{"filename": "main.mp4", "side": "zone.png"}]}]},
            "/groups": {"data": [{"logo": "logo.png"}, {"logo": None}, {}]},
        })

        self.assertEqual(api.get_unused_assets(), ["free.png"])

    def test_a_playlist_used_as_an_additional_one_or_in_a_zone_is_not_unused(self):
        api = self.make_api({
            "/playlists": {"data": [{"name": "Host", "assets": [{"filename": "x", "bottom": "InZone"}]}]},
        })
        api.get_playlist_names = MagicMock(return_value=["InGroup", "InZone", "Additional", "Free"])
        api.get_groups_playlists = MagicMock(return_value={"G": [("InGroup", None, None, None, None)]})
        api.get_player_objects = MagicMock(return_value=[{"playlists": ["Additional"]}, {"playlists": None}, {}])

        self.assertEqual(api.get_unused_playlists(), ["Free"])

    def test_a_label_of_a_playlist_or_a_location_is_not_unused(self):
        api = self.make_api({
            "/playlists": {"data": [{"labels": ["OfPlaylist"]}, {"labels": None}]},
            "/locations": {"data": [{"labels": ["OfLocation"]}, {}]},
        })
        api.get_labels = MagicMock(return_value=["OfPlayer", "OfPlaylist", "OfLocation", "Free"])
        api.get_player_labels = MagicMock(return_value=[("p", ["OfPlayer"])])
        api.get_group_labels = MagicMock(return_value=[])
        api.get_assets_labels = MagicMock(return_value=[])

        self.assertEqual(api.get_unused_labels(), ["Free"])


class DeletingUnusedTest(unittest.TestCase):
    def setUp(self):
        self.server = MagicMock()
        self.server.get_playlist_names.return_value = ["A", "B", "C"]
        self.server.get_unused_playlists.return_value = ["B", "C"]
        self.server.get_playlists_by_label.return_value = []

    def processor(self, processor_class=RemoveUnusedPlaylistsProcessor):
        processor, logger, patcher = make_processor(processor_class, self.server)
        self.addCleanup(patcher.stop)
        return processor, logger

    def test_a_name_that_is_in_use_is_refused_when_the_list_is_loaded(self):
        processor, logger = self.processor()

        with self.assertRaises(FormatException):
            processor.load("A\nB")

        logger.warning.assert_any_call("not_unused")
        self.server.delete_playlist.assert_not_called()

    def test_names_that_are_unused_are_accepted_and_offered_for_the_confirmation(self):
        processor, _ = self.processor()

        processor.load("B\nC")

        self.assertCountEqual(processor.items_to_confirm(), ["B", "C"])

    def test_something_that_gets_used_after_the_question_is_not_deleted(self):
        processor, logger = self.processor()
        processor.load("B\nC")
        self.server.get_unused_playlists.return_value = ["C"]  # B has been put to use in the meantime

        list(processor.run())

        self.server.delete_playlist.assert_called_once_with("C")
        logger.warning.assert_any_call("not_unused_now")

    def test_delete_all_unused_offers_exactly_what_the_server_calls_unused(self):
        processor, _ = self.processor(RemoveAllUnusedPlaylistsProcessor)

        processor.load("")

        self.assertCountEqual(processor.items_to_confirm(), ["B", "C"])

    def test_delete_all_unused_checks_again_before_deleting(self):
        processor, _ = self.processor(RemoveAllUnusedPlaylistsProcessor)
        processor.load("")
        self.server.get_unused_playlists.return_value = ["B"]

        list(processor.run())

        self.server.delete_playlist.assert_called_once_with("B")

    def test_every_kind_of_unused_entity_is_checked_against_the_server(self):
        cases = (
            (RemoveUnusedAssetsProcessor, "get_asset_names", "get_unused_assets"),
            (RemoveUnusedLabelsProcessor, "get_labels", "get_unused_labels"),
        )
        for processor_class, names_method, unused_method in cases:
            with self.subTest(processor=processor_class.__name__):
                server = MagicMock()
                getattr(server, names_method).return_value = ["used", "free"]
                getattr(server, unused_method).return_value = ["free"]
                refusing, _, patcher = make_processor(processor_class, server)
                self.addCleanup(patcher.stop)
                processor, _, patcher = make_processor(processor_class, server)
                self.addCleanup(patcher.stop)

                with self.assertRaises(FormatException):
                    refusing.load("used")
                processor.load("free")

                getattr(server, unused_method).assert_called()
                self.assertEqual(processor.items_to_confirm(), ["free"])

    def test_a_connection_error_while_checking_stops_the_load(self):
        import requests
        self.server.get_unused_playlists.side_effect = requests.exceptions.ConnectionError("down")
        processor, _ = self.processor()

        with self.assertRaises(InternalException):
            processor.load("B")

    def test_actions_that_do_not_delete_for_good_ask_nothing(self):
        processor, _, patcher = make_processor(RemovePlaylistsProcessor, self.server)
        self.addCleanup(patcher.stop)

        self.assertIsNone(processor.items_to_confirm())


class MessagesTest(unittest.TestCase):
    def test_the_new_messages_exist_in_both_languages(self):
        with open(MESSAGES, encoding="utf-8") as file:
            messages = json.load(file)
        keys = ("empty_keyword", "not_unused", "not_unused_now", "confirm_remove_title", "confirm_remove_text",
                "confirm_remove_more", "operation_cancelled", "cancelled")

        for language in ("cz", "en"):
            for key in keys:
                with self.subTest(language=language, key=key):
                    self.assertTrue(messages[language].get(key))


class ConfirmationInTheLogWindowTest(unittest.TestCase):
    """The question asked in the window between loading the input and the first deletion."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        path = os.path.join(self.directory.name, "logins.json")
        with open(path, "w", encoding="utf-8") as file:
            json.dump({"lang": "cz", "font": ["Helvetica", 12], "default": ["", ""], "logins": {}}, file)
        patcher = patch("gui_app.gui.credentials.get_password", return_value="")
        patcher.start()
        self.addCleanup(patcher.stop)
        try:
            self.app = gui.DSMediaplayApp(path)
        except tk.TclError:
            self.skipTest("no display available")
        self.addCleanup(self.app.destroy)
        self.app.update()

    def open_box(self, items):
        processor = MagicMock()
        processor.items_to_confirm.return_value = items
        processor.run.return_value = iter([])
        with patch("gui_app.log_box.ThreadManager.start_thread"), \
                patch("gui_app.log_box.ProcessorFactory.create_processor", return_value=processor):
            box = LoggingTextBox("remove_unused_playlists", url="http://example.com", login="u", password="p",
                                 data="", master=self.app)
            self.addCleanup(lambda: box.winfo_exists() and box.destroy())
            self.app.update()
            worker = threading.Thread(target=box.run_input_processing, daemon=True)
            deadline = time.monotonic() + 10

            def stop_when_done():
                if worker.is_alive() and time.monotonic() < deadline:
                    self.app.after(20, stop_when_done)
                else:
                    self.app.quit()

            worker.start()
            self.app.after(20, stop_when_done)
            # Like in the application: the worker thread can only reach Tk while the main thread is in its main loop
            self.app.mainloop()
            self.assertFalse(worker.is_alive(), "the worker is stuck")
        return box, processor

    def test_a_refusal_deletes_nothing_and_says_so(self):
        with patch("gui_app.log_box.messagebox.askyesno", return_value=False) as ask:
            box, processor = self.open_box(["x", "y"])

        ask.assert_called_once()
        processor.run.assert_not_called()
        self.assertEqual(box.indication_label.cget("text"), "Zrušeno")
        self.assertIn("nic nebylo smazáno", box.log_text.get("1.0", tk.END))

    def test_the_question_lists_what_will_be_deleted_and_defaults_to_no(self):
        with patch("gui_app.log_box.messagebox.askyesno", return_value=False) as ask:
            self.open_box(["alpha", "beta"])

        title, text = ask.call_args.args
        self.assertIn("alpha", text)
        self.assertIn("beta", text)
        self.assertIn("2", text)
        self.assertEqual(ask.call_args.kwargs["default"], "no")

    def test_a_long_list_is_cut_but_the_count_is_complete(self):
        items = [f"item{i}" for i in range(40)]
        with patch("gui_app.log_box.messagebox.askyesno", return_value=False) as ask:
            self.open_box(items)

        text = ask.call_args.args[1]
        self.assertIn("40", text)
        self.assertIn("item0", text)
        self.assertNotIn("item39", text)
        self.assertIn("25", text)  # "... and 25 more"

    def test_agreeing_runs_the_action(self):
        with patch("gui_app.log_box.messagebox.askyesno", return_value=True):
            box, processor = self.open_box(["x"])

        processor.run.assert_called_once()
        self.assertEqual(box.indication_label.cget("text"), "Hotovo")

    def test_an_action_that_deletes_nothing_for_good_asks_nothing(self):
        for items in (None, []):
            with self.subTest(items=items):
                with patch("gui_app.log_box.messagebox.askyesno") as ask:
                    _, processor = self.open_box(items)

                ask.assert_not_called()
                processor.run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
