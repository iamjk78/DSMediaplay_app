"""The files of a group (`assets`). The server does not work them out of the playlists of the group: it keeps what a client
sends and copies it to the players on Deploy. A group written with playlists and without their files has the names of the
playlists on its players and nothing to play. So every write of the playlists of a group sends the files too, worked out as
the web interface does it."""
import copy
import unittest
from unittest.mock import MagicMock

from api_testing.request_calls import ServerApi, prepare_group_playlists


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

    def request(self, method, endpoint, **kwargs):
        self.reads.append((method, endpoint))
        if method == "get" and endpoint == "/playlists":
            return {"success": True, "data": copy.deepcopy(self.playlists)}
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

    def test_removing_playlists_by_a_keyword_or_the_expired_ones_leaves_the_files_of_the_rest_too(self):
        expired = {"name": "Kofola", "plType": "regular", "skipForSchedule": False,
                   "settings": {"durationEnable": "true", "enddate": "2020-01-01T00:00:00.000Z"}}
        group = {**GROUP, "playlists": GROUP["playlists"] + [expired],
                 "assets": ["d.mp4", "__Default.json", "kofola1.mp4", "kofola2.jpg", "__Kofola.json"]}
        for remove in (lambda api: api.remove_playlists_by_keyword_from_group("Shop1", "Kofo"),
                       lambda api: api.remove_expired_playlists_from_group("Shop1")):
            with self.subTest(remove=remove):
                api, server = api_with([group], PLAYLISTS)

                self.assertEqual(remove(api), ["Kofola"])

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


if __name__ == "__main__":
    unittest.main()
