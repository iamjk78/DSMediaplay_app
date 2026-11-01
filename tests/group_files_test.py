"""The files of a group (`assets`). The server does not work them out of the playlists of the group: it keeps what a client
sends and copies it to the players on Deploy. A group written with playlists and without their files has the names of the
playlists on its players and nothing to play. So every write of the playlists of a group sends the files too, worked out as
the web interface does it; and a group that was written without them can be repaired."""
import copy
import unittest
from unittest.mock import MagicMock, patch

from api_testing.request_calls import ServerApi, prepare_group_playlists
from destructive_actions_test import make_processor
from main_buttons_test import MainWindowCase
from processor.input_processing import InternalException, RepairGroupFilesProcessor


def playlist(name, files=(), layout="1", settings=None, template=None, rows=None):
    """A playlist as the server has it: rows with a main file and perhaps files in the zones of its layout."""
    data = {"name": name, "layout": layout, "settings": settings if settings is not None else {},
            "assets": rows if rows is not None else [{"filename": file} for file in files]}
    if template:
        data["templateName"] = template
    return data


def entry(name, **settings):
    return {"name": name, "settings": settings}


class FilesOfAGroupTest(unittest.TestCase):
    def files(self, entries, playlists, logo=None):
        return prepare_group_playlists(entries, playlists, logo)[1]

    def test_a_group_has_the_files_of_its_playlists_and_the_file_of_every_playlist(self):
        files = self.files([entry("Kofola")], [playlist("Kofola", ["a.mp4", "b.jpg"])])

        self.assertEqual(files, ["a.mp4", "b.jpg", "__Kofola.json"])

    def test_the_playlists_are_taken_from_the_last_to_the_first_like_the_interface_does(self):
        files = self.files([entry("One"), entry("Two")], [playlist("One", ["1.mp4"]), playlist("Two", ["2.mp4"])])

        self.assertEqual(files, ["2.mp4", "__Two.json", "1.mp4", "__One.json"])

    def test_a_file_that_is_in_more_playlists_is_there_once(self):
        files = self.files([entry("One"), entry("Two")], [playlist("One", ["x.mp4", "1.mp4"]), playlist("Two", ["x.mp4"])])

        self.assertEqual(sorted(files), ["1.mp4", "__One.json", "__Two.json", "x.mp4"])
        self.assertEqual(len(files), len(set(files)))

    def test_the_same_playlist_twice_in_a_group_gives_its_files_once(self):
        files = self.files([entry("One"), entry("One")], [playlist("One", ["1.mp4"])])

        self.assertEqual(files, ["1.mp4", "__One.json"])

    def test_the_files_of_the_system_are_not_files_of_the_group(self):
        rows = [{"filename": "_system_clock.png", "side": "_system_side.png"}, {"filename": "real.mp4"}]

        files = self.files([entry("P")], [playlist("P", layout="2a", rows=rows)])

        self.assertEqual(files, ["real.mp4", "__P.json"])

    def test_only_the_zones_of_the_layout_count(self):
        rows = [{"filename": "main.mp4", "side": "side.mp4", "bottom": "bottom.mp4", "zone4": "four.mp4"}]
        expected = {"1": ["main.mp4"], "2a": ["main.mp4", "side.mp4"], "3a": ["main.mp4", "side.mp4", "bottom.mp4"],
                    "2bp": ["main.mp4", "bottom.mp4"],
                    "custom": ["main.mp4", "side.mp4", "bottom.mp4", "four.mp4"]}
        for layout, names in expected.items():
            with self.subTest(layout=layout):
                self.assertEqual(self.files([entry("P")], [playlist("P", layout=layout, rows=rows)]),
                                 names + ["__P.json"])

    def test_a_layout_that_is_not_known_looks_in_every_zone(self):
        rows = [{"filename": "m.mp4", "zone6": "six.mp4"}]

        self.assertIn("six.mp4", self.files([entry("P")], [playlist("P", layout="future", rows=rows)]))

    def test_a_playlist_in_a_zone_brings_its_own_files_one_level_deep(self):
        rows = [{"filename": "m.mp4", "side": "__Nested.json"}]
        nested = playlist("Nested", rows=[{"filename": "n.mp4", "side": "__Deeper.json"}])
        deeper = playlist("Deeper", ["d.mp4"])

        files = self.files([entry("P")], [playlist("P", layout="2a", rows=rows), nested, deeper])

        self.assertEqual(files, ["m.mp4", "__Nested.json", "n.mp4", "__P.json"])
        self.assertNotIn("d.mp4", files)

    def test_the_default_template_name_of_a_layout_that_is_not_custom_is_no_file(self):
        files = self.files([entry("P")], [playlist("P", ["a.mp4"], layout="2a", template="custom_layout.html")])

        self.assertEqual(files, ["a.mp4", "__P.json"])

    def test_a_template_and_the_logo_of_the_group_are_files_of_it(self):
        files = self.files([entry("P")], [playlist("P", ["a.mp4"], layout="custom", template="template.html")], logo="logo.png")

        self.assertEqual(files, ["a.mp4", "__P.json", "template.html", "logo.png"])

    def test_the_logo_is_not_repeated_when_a_playlist_has_it(self):
        self.assertEqual(self.files([entry("P")], [playlist("P", ["logo.png"])], logo="logo.png").count("logo.png"), 1)

    def test_a_playlist_the_server_does_not_have_adds_no_file_and_stays_in_the_group(self):
        entries, files = prepare_group_playlists([entry("Gone")], [playlist("Other", ["o.mp4"])])

        self.assertEqual(files, [])
        self.assertEqual(entries, [entry("Gone")])

    def test_an_entry_without_a_name_is_dropped(self):
        entries, _ = prepare_group_playlists([{"settings": {}}, entry("P")], [playlist("P", ["a.mp4"])])

        self.assertEqual([e["name"] for e in entries], ["P"])

    def test_the_arguments_are_not_changed(self):
        entries, playlists = [entry("P", durationEnable="true")], [playlist("P", ["a.mp4"], settings={"audio": {"enable": True}})]
        before = copy.deepcopy((entries, playlists))

        prepare_group_playlists(entries, playlists)

        self.assertEqual((entries, playlists), before)


class EntriesOfAGroupTest(unittest.TestCase):
    def one(self, existing, **kwargs):
        entries, _ = prepare_group_playlists([existing], [playlist("P", **kwargs)])
        return entries[0]

    def test_a_regular_playlist_is_a_regular_entry_that_is_not_skipped(self):
        result = self.one(entry("P"), files=["a.mp4"])

        self.assertEqual((result["plType"], result["skipForSchedule"]), ("regular", False))

    def test_a_playlist_without_files_is_marked_so_and_skipped(self):
        result = self.one(entry("P"), files=[])

        self.assertEqual((result["plType"], result["skipForSchedule"]), ("no assets", True))

    def test_the_special_playlist_is_special_and_is_not_asked_about_its_files(self):
        entries, _ = prepare_group_playlists([entry("TV_OFF")], [playlist("TV_OFF", files=[])])

        self.assertEqual(entries[0]["plType"], "special")
        self.assertNotIn("skipForSchedule", entries[0])

    def test_the_kind_follows_what_the_playlist_does(self):
        for settings, expected in (({"ads": {"adPlaylist": True}}, "advt"), ({"domination": {"enable": True}}, "domination"),
                                   ({"event": {"enable": True}}, "event"), ({"keyPress": {"enable": True}}, "keyPress"),
                                   ({"audio": {"enable": True}}, "audio"), ({"audio": {"enable": False}}, "regular"),
                                   ({"ads": {"adPlaylist": False}}, "regular"), ({"ads": True}, "regular"), ({}, "regular")):
            with self.subTest(settings=settings):
                self.assertEqual(self.one(entry("P"), files=["a"], settings=settings)["plType"], expected)

    def test_the_first_that_applies_wins(self):
        settings = {"audio": {"enable": True}, "domination": {"enable": True}, "ads": {"adPlaylist": True}}

        self.assertEqual(self.one(entry("P"), files=["a"], settings=settings)["plType"], "advt")

    def test_the_string_false_counts_as_true_like_in_the_interface(self):
        self.assertEqual(self.one(entry("P"), files=["a"], settings={"event": {"enable": "false"}})["plType"], "event")

    def test_what_the_playlist_says_is_taken_over_and_what_it_does_not_say_is_dropped(self):
        existing = entry("P", ads={"old": 1}, audio={"enable": True}, durationEnable="true", startdate="2026-01-01")

        result = self.one(existing, files=["a"], settings={"audio": {"enable": False}, "domination": {"enable": False},
                                                          "onlineOnly": True})

        self.assertEqual(result["settings"], {"audio": {"enable": False}, "domination": {"enable": False}, "onlineOnly": True,
                                              "durationEnable": "true", "startdate": "2026-01-01"})

    def test_an_entry_without_settings_gets_them(self):
        result = self.one({"name": "P"}, files=["a"], settings={"onlineOnly": True})

        self.assertEqual(result["settings"], {"onlineOnly": True})


class FakeServer:
    """A server with groups and playlists: what is asked for is read, what is posted is kept."""

    def __init__(self, groups, playlists):
        self.groups = {group["_id"]: copy.deepcopy(group) for group in groups}
        self.playlists = playlists
        self.posts = []
        self.reads = []
        self.account_files = []

    def request(self, method, endpoint, **kwargs):
        self.reads.append((method, endpoint))
        if method == "get" and endpoint == "/playlists":
            return {"success": True, "data": copy.deepcopy(self.playlists)}
        if method == "get" and endpoint == "/files":
            return {"success": True, "data": {"dbdata": [{"name": name} for name in self.account_files]}}
        if method == "get" and endpoint == "/groups":
            if kwargs.get("params"):
                return {"success": True, "data": [g for g in copy.deepcopy(list(self.groups.values()))
                                                  if g["name"] == kwargs["params"]["string"]]}
            return {"success": True, "data": copy.deepcopy(list(self.groups.values()))}
        if method == "get" and endpoint.startswith("/groups/"):
            return {"success": True, "data": copy.deepcopy(self.groups[endpoint.rsplit("/", 1)[1]])}
        if method == "post" and endpoint.startswith("/groups/"):
            body = copy.deepcopy(kwargs["json"])
            self.posts.append(body)
            self.groups[body["_id"]].update(body)  # the server merges what it is sent
            return {"success": True, "data": body}
        raise AssertionError(f"unexpected request {method} {endpoint}")


def api_with(groups, playlists):
    server = FakeServer(groups, playlists)
    api = ServerApi.__new__(ServerApi)
    api._make_request = MagicMock(side_effect=server.request)
    return api, server


PLAYLISTS = [playlist("Default", ["d.mp4"]), playlist("Kofola", ["kofola1.mp4", "kofola2.jpg"]),
             playlist("CAMEL", ["camel.mp4"], settings={"audio": {"enable": False}})]
GROUP = {"_id": "g1", "name": "Shop1", "logo": "logo.png", "assets": ["d.mp4", "__Default.json"],
         "playlists": [{"name": "Default", "plType": "regular", "skipForSchedule": False, "settings": {}}]}


class WritingAGroupTest(unittest.TestCase):
    def test_a_playlist_that_is_added_to_a_group_brings_its_files_to_the_group(self):
        api, server = api_with([GROUP], PLAYLISTS)

        api.set_playlist_to_group_detailed("Shop1", [("Default", None, None, None, None, None),
                                                     ("Kofola", None, None, None, "00:00", "23:59")])

        body = server.posts[-1]
        self.assertEqual([p["name"] for p in body["playlists"]], ["Default", "Kofola"])
        for name in ("kofola1.mp4", "kofola2.jpg", "__Kofola.json", "d.mp4", "__Default.json", "logo.png"):
            self.assertIn(name, body["assets"])
        self.assertEqual(len(body["assets"]), len(set(body["assets"])))

    def test_the_body_is_what_it_was_and_the_files(self):
        api, server = api_with([GROUP], PLAYLISTS)

        api.set_playlist_to_group_detailed("Shop1", [("Kofola", None, None, None, None, None)])

        self.assertEqual(sorted(server.posts[-1]), ["_id", "assets", "name", "playAllEligiblePlaylists", "playlists"])
        self.assertEqual(server.posts[-1]["playAllEligiblePlaylists"], "true")

    def test_the_new_entry_gets_the_type_the_interface_gives_it(self):
        api, server = api_with([GROUP], PLAYLISTS)

        api.set_playlist_to_group_detailed("Shop1", [("CAMEL", None, None, None, None, None)])

        written = server.posts[-1]["playlists"][0]
        self.assertEqual((written["plType"], written["skipForSchedule"]), ("regular", False))
        self.assertEqual(written["settings"]["audio"], {"enable": False})

    def test_the_simple_setting_sends_the_files_too(self):
        api, server = api_with([GROUP], PLAYLISTS)

        api.set_playlist_to_group("Shop1", [("Kofola", None, None, None, None)])

        self.assertIn("kofola1.mp4", server.posts[-1]["assets"])

    def test_removing_a_playlist_from_all_groups_leaves_the_files_of_the_rest(self):
        group = {**GROUP, "playlists": GROUP["playlists"] + [{"name": "Kofola", "settings": {}}],
                 "assets": ["d.mp4", "__Default.json", "kofola1.mp4", "kofola2.jpg", "__Kofola.json"]}
        api, server = api_with([group], PLAYLISTS)

        api.remove_playlists_from_groups(["Kofola"])

        body = server.posts[-1]
        self.assertEqual([p["name"] for p in body["playlists"]], ["Default"])
        self.assertEqual(sorted(body["assets"]), ["__Default.json", "d.mp4", "logo.png"])

    def test_the_playlists_of_the_account_are_read_once_for_the_whole_session(self):
        second = {**GROUP, "_id": "g2", "name": "Shop2"}
        api, server = api_with([GROUP, second], PLAYLISTS)

        for name in ("Shop1", "Shop2"):
            api.set_playlist_to_group_detailed(name, [("Kofola", None, None, None, None, None)])

        self.assertEqual(server.reads.count(("get", "/playlists")), 1)
        self.assertEqual(len(server.posts), 2)


class RepairPlanTest(unittest.TestCase):
    BROKEN = {"_id": "g2", "name": "Shop2", "logo": None, "assets": ["d.mp4", "__Default.json"],
              "playlists": [{"name": "Default", "plType": "regular", "skipForSchedule": False, "settings": {}},
                            {"name": "Kofola", "settings": {}}]}  # added by the old write: no files, no type
    FINE = {"_id": "g1", "name": "Shop1", "logo": None,
            "assets": ["kofola2.jpg", "__Kofola.json", "kofola1.mp4", "d.mp4", "__Default.json"],
            "playlists": [{"name": "Default", "plType": "regular", "skipForSchedule": False, "settings": {}},
                          {"name": "Kofola", "plType": "regular", "skipForSchedule": False, "settings": {}}]}

    def test_only_the_groups_that_lack_files_are_planned_and_all_are_counted(self):
        api, _ = api_with([self.FINE, self.BROKEN], PLAYLISTS)

        plan, total = api.plan_group_files_repair()

        self.assertEqual((total, [item["name"] for item in plan]), (2, ["Shop2"]))

    def test_the_missing_files_are_added_and_none_is_taken_away(self):
        broken = {**self.BROKEN, "assets": ["d.mp4", "__Default.json", "something-else.mp4"]}
        api, _ = api_with([broken], PLAYLISTS)

        item = api.plan_group_files_repair()[0][0]

        self.assertEqual(item["assets"][:3], ["d.mp4", "__Default.json", "something-else.mp4"])
        self.assertEqual(sorted(item["missing"]), ["__Kofola.json", "kofola1.mp4", "kofola2.jpg"])
        self.assertEqual(sorted(item["assets"]), sorted(["d.mp4", "__Default.json", "something-else.mp4"] + item["missing"]))

    def test_a_template_that_is_no_file_of_the_account_is_taken_away_but_a_real_one_stays(self):
        group = {**self.FINE, "assets": self.FINE["assets"] + ["custom_layout.html", "custom_layout2.html", "x.mp4"]}
        api, server = api_with([group], PLAYLISTS)
        server.account_files = ["custom_layout2.html"]

        item = api.plan_group_files_repair()[0][0]

        self.assertEqual(item["stray"], ["custom_layout.html"])
        self.assertEqual(item["assets"], self.FINE["assets"] + ["custom_layout2.html", "x.mp4"])

    def test_an_entry_without_the_type_gets_it_and_the_others_stay_as_they_are(self):
        api, _ = api_with([self.BROKEN], PLAYLISTS)

        item = api.plan_group_files_repair()[0][0]

        self.assertEqual(item["playlists"][0], self.BROKEN["playlists"][0])
        self.assertEqual((item["playlists"][1]["plType"], item["playlists"][1]["skipForSchedule"]), ("regular", False))
        self.assertEqual(item["entries_changed"], 1)

    def test_an_entry_that_has_its_type_is_not_touched_even_when_the_interface_would_say_something_else(self):
        group = {**self.FINE, "playlists": [{"name": "Default", "plType": "audio", "skipForSchedule": False,
                                            "settings": {"audio": {"enable": True}}}], "assets": ["d.mp4", "__Default.json"]}
        api, _ = api_with([group], PLAYLISTS)

        plan, _ = api.plan_group_files_repair()

        self.assertEqual(plan, [])

    def test_a_group_without_playlists_needs_nothing(self):
        api, _ = api_with([{"_id": "g3", "name": "Empty", "assets": [], "playlists": []}], PLAYLISTS)

        self.assertEqual(api.plan_group_files_repair(), ([], 1))

    def test_what_is_written_is_the_files_and_the_entries_of_that_group_only(self):
        api, server = api_with([self.BROKEN], PLAYLISTS)
        item = api.plan_group_files_repair()[0][0]

        api.write_group_files(item)

        body = server.posts[-1]
        self.assertEqual(sorted(body), ["_id", "assets", "name", "playlists"])
        self.assertEqual(server.groups["g2"]["assets"], item["assets"])

    def test_after_the_repair_the_group_is_fine(self):
        api, server = api_with([self.BROKEN], PLAYLISTS)
        api.write_group_files(api.plan_group_files_repair()[0][0])
        api._playlist_cache = None

        self.assertEqual(api.plan_group_files_repair(), ([], 1))


class RepairProcessorTest(unittest.TestCase):
    def processor(self, plan, total=None, **server_kwargs):
        server = MagicMock()
        server.plan_group_files_repair.return_value = (plan, len(plan) + 2 if total is None else total)
        server.__enter__.return_value = server
        for name, value in server_kwargs.items():
            getattr(server, name).side_effect = value
        processor, logger, patcher = make_processor(RepairGroupFilesProcessor, server, real_text=True)
        self.addCleanup(patcher.stop)
        return processor, logger, server

    @staticmethod
    def item(name, missing=("a.mp4",), entries=1):
        return {"id": name, "name": name, "playlists": [], "assets": list(missing), "missing": list(missing),
                "entries_changed": entries, "stray": []}

    def test_it_says_how_many_groups_need_the_repair(self):
        processor, logger, _ = self.processor([self.item("G1"), self.item("G2")], total=10)

        processor.load("")

        self.assertIn("Skupin celkem: 10, k opravě: 2, v pořádku: 8.", [c.args[0] for c in logger.info.call_args_list])

    def test_it_asks_with_the_names_and_the_count_and_says_deploy_is_still_to_come(self):
        processor, _, _ = self.processor([self.item("G1"), self.item("G2")])
        processor.load("")

        question = processor.confirmation()

        self.assertIn("(2)", question.text)
        self.assertIn("• G1", question.text)
        self.assertIn("Deploy", question.text)

    def test_when_nothing_needs_the_repair_nothing_is_asked_and_nothing_is_written(self):
        processor, logger, server = self.processor([])
        processor.load("")

        self.assertIsNone(processor.confirmation())
        list(processor.run())

        server.write_group_files.assert_not_called()
        self.assertIn("není co opravovat", " ".join(c.args[0] for c in logger.info.call_args_list))

    def test_every_planned_group_is_written_and_reported(self):
        processor, logger, server = self.processor([self.item("G1", ("a.mp4", "b.mp4")), self.item("G2", ())])
        processor.load("")

        list(processor.run())

        self.assertEqual([c.args[0]["name"] for c in server.write_group_files.call_args_list], ["G1", "G2"])
        lines = [c.args[0] for c in logger.info.call_args_list]
        self.assertIn("Skupina G1: doplněno souborů: 2 (a.mp4, b.mp4), upravených položek playlistů: 1, odebráno nepoužitých souborů: 0.", lines)
        self.assertIn("Skupina G2: doplněno souborů: 0, upravených položek playlistů: 1, odebráno nepoužitých souborů: 0.", lines)

    def test_a_long_list_of_added_files_is_cut(self):
        processor, logger, _ = self.processor([self.item("G1", tuple(f"f{n}.mp4" for n in range(8)))])
        processor.load("")

        list(processor.run())

        line = next(c.args[0] for c in logger.info.call_args_list if c.args[0].startswith("Skupina G1"))
        self.assertIn("f4.mp4", line)
        self.assertNotIn("f5.mp4", line)
        self.assertIn("a dalších 3", line)

    def test_a_connection_that_is_lost_stops_it_and_says_what_is_left(self):
        import requests
        processor, logger, server = self.processor([self.item("G1"), self.item("G2"), self.item("G3")],
                                                   write_group_files=[None, requests.exceptions.ConnectTimeout()])
        processor.load("")

        with self.assertRaises(InternalException):
            list(processor.run())

        errors = [c.args[0] for c in logger.error.call_args_list]
        self.assertIn("Server neodpovídá", errors[0])
        self.assertEqual(errors[1], "Přerušeno po 1 z 3 krocích. Nezpracováno nebo nepotvrzeno (2): G2, G3")


class RegistrationTest(unittest.TestCase):
    def test_the_action_is_among_the_group_actions_in_both_languages_and_needs_no_input(self):
        import json
        import os
        from util.actions import action_kind, action_needs_input, entity_actions
        with open(os.path.join(os.path.dirname(__file__), "..", "assets", "messages.json"), encoding="utf-8") as file:
            messages = json.load(file)
        for language in ("cz", "en"):
            keys = list(entity_actions(messages[language]["actions"])["Groups"].values())
            self.assertIn("set_group_files_repair", keys)
        self.assertFalse(action_needs_input("set_group_files_repair"))
        self.assertEqual(action_kind("set_group_files_repair"), "change")

    def test_the_processor_and_the_backup_know_it_under_one_name(self):
        from processor.input_processing import ProcessorFactory
        from util import backup
        processor = ProcessorFactory.create_processor("group_files_repair", MagicMock(), "https://x", "u", "p", MagicMock())

        self.assertIsInstance(processor, RepairGroupFilesProcessor)
        self.assertTrue(backup.csv_tasks_for("group_files_repair"))


class RepairWindowTest(MainWindowCase):
    def test_the_window_makes_its_log_window_for_the_action(self):
        from gui_app.log_box import GroupFilesRepairLogBox, LoggingTextBoxFactory
        with patch("gui_app.log_box.ThreadManager.start_thread"):
            box = LoggingTextBoxFactory.create_log_box("group_files_repair", self.app, "https://x", "u", "p", "Non-empty")
        self.addCleanup(lambda: box.winfo_exists() and box.destroy())

        self.assertIsInstance(box, GroupFilesRepairLogBox)
        self.assertEqual(box.processor_type, "group_files_repair")

    def test_the_action_is_offered_in_the_list_of_the_groups_and_starts_without_an_input(self):
        self.app.entity_type_var.set("Groups")
        self.app.update_action_selection()

        label = next(label for label, key in self.app.entity_actions["Groups"].items() if key == "set_group_files_repair")

        self.assertIn(label, self.app.option_choose_action["values"])
        self.assertEqual(label, "Oprava - soubory skupin")


if __name__ == "__main__":
    unittest.main()
