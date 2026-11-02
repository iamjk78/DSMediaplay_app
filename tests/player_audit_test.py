"""What a player has after a deploy against what the server says: the digests worked out by the script that runs on
the player are the same as those worked out here, and the differences are named."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from util import player_audit as audit

PLAYLIST = {"name": "P", "layout": "1", "settings": {"ads": {"adCount": 1}, "audio": {"enable": False}},
            "assets": [{"filename": "b.mp4", "duration": 5, "selected": True}, {"filename": "á ř.jpg", "duration": 10}],
            "labels": ["x"], "version": 3, "belongsTo": "x", "templateName": None}
GROUP = {"name": "G", "deployedPlaylists": [{"name": "P", "plType": "regular", "settings": {"durationEnable": False}}],
         "playlists": [{"name": "P", "plType": "regular", "settings": {"durationEnable": False}}],
         "assets": ["b.mp4", "á ř.jpg", "__P.json"], "deployedAssets": ["b.mp4", "á ř.jpg", "__P.json"],
         "assetsValidity": [{"name": "á ř.jpg", "startdate": "2022-04-26T00:00:00.000Z"}], "combineDefaultPlaylist": True,
         "kioskUi": {"enable": True}, "name_of_nothing": 1}
FILES = ["b.mp4", "á ř.jpg", "__P.json"]


class PlayerFolders:
    """A player's folders in a temp folder, filled the way a deployed player has them."""

    def __init__(self, test):
        directory = tempfile.TemporaryDirectory()
        test.addCleanup(directory.cleanup)
        self.media = os.path.join(directory.name, "media")
        self.config = os.path.join(directory.name, "config")
        os.makedirs(self.media)
        os.makedirs(self.config)
        self.write("b.mp4", b"1234")
        self.write("á ř.jpg", b"12")
        self.write("__P.json", json.dumps(PLAYLIST).encode())
        self.json("_settings.json", {"combineDefaultPlaylist": True, "kioskUi": {"enable": True}, "sleep": "own",
                                     "assetsValidity": GROUP["assetsValidity"]})
        self.json("_config.json", {"deployedPlaylists": GROUP["deployedPlaylists"]})

    def write(self, name, content):
        with open(os.path.join(self.media, name), "wb") as file:
            file.write(content)

    def json(self, name, data):
        with open(os.path.join(self.config, name), "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False)

    def report(self):
        """What the script prints when it runs (here, with this python) over these folders."""
        done = subprocess.run([sys.executable, "-I", "-c", audit.script(self.media, self.config)], capture_output=True,
                              text=True, check=True)
        return json.loads(done.stdout)


def expected(group=None, playlists=None, files=FILES, sizes=None):
    return audit.expected_audit(group or GROUP, playlists or {"P": PLAYLIST}, files,
                                {"b.mp4": (4, 1)} if sizes is None else sizes)


class ScriptAndServerAgreeTest(unittest.TestCase):
    def test_a_player_that_has_what_was_deployed_differs_in_nothing(self):
        report = PlayerFolders(self).report()

        result = audit.compare_audit(expected(), report)

        self.assertFalse(audit.has_differences(result), result)

    def test_the_script_reports_the_sizes_of_the_files_and_digests_not_the_contents(self):
        report = PlayerFolders(self).report()

        self.assertEqual(report["files"]["b.mp4"], 4)
        self.assertEqual(sorted(report["playlists"]["P"]), sorted((*audit.PLAYLIST_PARTS, "order", "rows")))
        self.assertNotIn("á ř.jpg", json.dumps(report["playlists"]))
        self.assertLess(len(json.dumps(report)), 2000)

    def test_a_missing_file_a_wrong_size_and_a_changed_order_are_named(self):
        folders = PlayerFolders(self)
        os.remove(os.path.join(folders.media, "á ř.jpg"))
        folders.write("b.mp4", b"1")
        changed = {**PLAYLIST, "assets": list(reversed(PLAYLIST["assets"]))}
        folders.write("__P.json", json.dumps(changed).encode())

        result = audit.compare_audit(expected(), folders.report())

        self.assertEqual(result["missing"], ["á ř.jpg"])
        self.assertEqual(result["wrong_size"], [("b.mp4", 4, 1)])
        self.assertEqual(result["different"]["playlists"], {"P": ["order"]})

    def test_a_changed_duration_is_a_change_of_the_rows_and_not_of_the_order(self):
        folders = PlayerFolders(self)
        rows = [dict(row) for row in PLAYLIST["assets"]]
        rows[0]["duration"] = 99
        folders.write("__P.json", json.dumps({**PLAYLIST, "assets": rows}).encode())

        result = audit.compare_audit(expected(), folders.report())

        self.assertEqual(result["different"]["playlists"], {"P": ["rows"]})

    def test_a_changed_validity_domination_or_setting_of_the_group_is_named(self):
        folders = PlayerFolders(self)
        folders.json("_config.json", {"deployedPlaylists": [{"name": "P", "plType": "domination",
                                                              "settings": {"domination": {"enable": True, "timeInterval": 5}}}]})
        folders.json("_settings.json", {"combineDefaultPlaylist": False, "kioskUi": {"enable": True}, "assetsValidity": []})

        different = audit.compare_audit(expected(), folders.report())["different"]

        self.assertTrue(different["deployed"])
        self.assertTrue(different["validity"])
        self.assertEqual(different["settings"], ["combineDefaultPlaylist"])

    def test_a_damaged_playlist_file_is_named(self):
        folders = PlayerFolders(self)
        folders.write("__P.json", b"{not json")

        result = audit.compare_audit(expected(), folders.report())

        self.assertEqual(result["different"]["playlists"], {"P": ["corrupt"]})

    def test_what_the_player_does_not_report_is_not_judged(self):
        result = audit.compare_audit(expected(), {"files": {name: None for name in FILES}})

        self.assertFalse(audit.has_differences(result), result)

    def test_a_setting_that_one_side_lacks_is_not_compared_and_the_own_ones_of_the_player_never_are(self):
        folders = PlayerFolders(self)
        folders.json("_settings.json", {"combineDefaultPlaylist": True, "sleep": "another", "name": "player"})  # no kioskUi

        different = audit.compare_audit(expected(), folders.report())["different"]

        self.assertEqual(different["settings"], [])

    def test_the_script_runs_on_python_37_syntax_and_leaves_the_files_as_they_were(self):
        folders = PlayerFolders(self)
        before = sorted((name, os.path.getmtime(os.path.join(folders.media, name))) for name in os.listdir(folders.media))

        folders.report()

        self.assertEqual(before, sorted((name, os.path.getmtime(os.path.join(folders.media, name)))
                                        for name in os.listdir(folders.media)))
        self.assertNotIn(":=", audit.script())  # the player has Python 3.7


TRICKY = "Q\"u'o\\te ✓ \U0001F600 PY\t$(x) `y`"


class DetailTest(unittest.TestCase):
    @staticmethod
    def read(want, folders):
        done = subprocess.run([sys.executable, "-I", "-c", audit.detail_script(want, folders.media, folders.config)],
                              capture_output=True, text=True, check=True)
        return json.loads(done.stdout)

    def test_what_differs_is_read_from_the_player_and_only_that(self):
        folders = PlayerFolders(self)
        changed = {**PLAYLIST, "assets": list(reversed(PLAYLIST["assets"])), "settings": {"ads": {"adCount": 9}}}
        folders.write("__P.json", json.dumps(changed).encode())
        folders.json("_settings.json", {"combineDefaultPlaylist": False, "kioskUi": {"enable": True}, "assetsValidity": []})
        want = audit.detail_request(audit.compare_audit(expected(), folders.report()))

        details = self.read(want, folders)

        self.assertEqual(want["playlists"], {"P": ["settings", "order"]})
        self.assertEqual(details["settings"], {"combineDefaultPlaylist": False})
        self.assertEqual(details["validity"], [])
        self.assertEqual(details["playlists"]["P"]["order"], ["á ř.jpg", "b.mp4"])
        self.assertNotIn("rows", details["playlists"]["P"])
        self.assertNotIn("deployed", details)

    def test_the_places_of_a_difference_name_the_value_on_the_server_and_on_the_player(self):
        folders = PlayerFolders(self)
        folders.json("_settings.json", {"combineDefaultPlaylist": False, "kioskUi": {"enable": True},
                                        "assetsValidity": [{"name": "á ř.jpg", "startdate": "2030"}]})
        changed = {**PLAYLIST, "assets": [dict(PLAYLIST["assets"][0], duration=99), PLAYLIST["assets"][1]]}
        folders.write("__P.json", json.dumps(changed).encode())
        result = audit.compare_audit(expected(), folders.report())

        places = audit.differences_in_detail(result, expected(), self.read(audit.detail_request(result), folders))

        self.assertEqual(places["settings"], {"combineDefaultPlaylist": [("", True, False)]})
        self.assertEqual(places["validity"], [("á ř.jpg.startdate", "2022-04-26T00:00:00.000Z", "2030")])
        self.assertEqual(places["playlists"], {"P": {"rows": [("b.mp4.duration", 5, 99)]}})

    def test_the_names_that_the_server_may_hold_cannot_break_out_of_the_command(self):
        for name in (TRICKY, "PY", "x'''\n PY\nimport os", "\"; rm -rf / #", "\\", " "):
            with self.subTest(name=name):
                folders = PlayerFolders(self)
                want = {"playlists": {name: ["layout"]}, "settings": [], "deployed": False, "validity": False}

                done = subprocess.run([sys.executable, "-I", "-c", audit.detail_script(want, folders.media, folders.config)],
                                      capture_output=True, text=True)

                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(set(json.loads(done.stdout)["playlists"]), {name})
                command = audit.detail_command(want)
                self.assertTrue(command.startswith("python3 - <<'PY'\n") and command.endswith("\nPY\n"))
                self.assertEqual([line for line in command.splitlines() if line == "PY"], ["PY"])  # only its end

    def test_nothing_that_has_a_value_differing_asks_for_nothing(self):
        result = audit.compare_audit(expected(), PlayerFolders(self).report())

        self.assertIsNone(audit.detail_request(result))

    def test_one_entry_more_on_one_side_is_named_and_does_not_make_the_others_differ(self):
        server = [{"name": "TV_OFF", "settings": {}}, {"name": "A", "settings": {"x": 1}}, {"name": "B", "settings": {"x": 2}},
                  {"name": "A", "settings": {"x": 3}}]
        player = [{"name": "TV_OFF", "settings": {}}, {"name": "B", "settings": {"x": 2}}, {"name": "A", "settings": {"x": 4}}]

        places = list(audit.walk_keyed(server, player, "name"))

        self.assertEqual(places, [("@only_server", ["A"], audit.MISSING), ("A.settings.x", 1, 4)])

    def test_the_same_entries_in_another_order_are_told_as_the_order_only(self):
        places = list(audit.walk_keyed([{"name": "A"}, {"name": "B"}], [{"name": "B"}, {"name": "A"}], "name"))

        self.assertEqual(places, [("@order", ["A", "B"], ["B", "A"])])

    def test_a_key_that_holds_null_is_a_key_that_is_not_there(self):
        self.assertEqual(list(audit.walk({"reboot": {"enable": True}}, {"reboot": {"enable": True, "time": None}})), [])
        self.assertEqual(audit.digest({"a": 1, "c": {}}), audit.digest({"a": 1, "b": None, "c": {"d": None}}))
        self.assertNotEqual(audit.digest({"a": 1}), audit.digest({"a": 1, "b": 0}))  # zero is a value

    def test_where_two_values_differ(self):
        places = list(audit.walk({"a": 1, "b": [1, 2, 3], "c": {"d": "x"}, "e": 1},
                                 {"a": 1, "b": [1, 5], "c": {"d": "y"}, "f": 2}))

        self.assertEqual(places, [("b[1]", 2, 5), ("b[2]", 3, audit.MISSING), ("c.d", "x", "y"),
                                  ("e", 1, audit.MISSING), ("f", audit.MISSING, 2)])

    def test_a_long_value_is_cut_and_what_one_side_lacks_is_said(self):
        self.assertEqual(audit.short_value(audit.MISSING), "<není>")
        self.assertEqual(audit.short_value("x" * 200)[-1], "…")
        self.assertEqual(audit.short_value({"a": "č"}), '{"a": "č"}')


class ExpectedTest(unittest.TestCase):
    def test_what_was_deployed_is_what_a_group_is_expected_to_have_and_what_changed_since_is_named(self):
        group = {**GROUP, "playlists": [{"name": "Other"}], "assets": ["x"]}

        result = audit.expected_audit(group, {"P": PLAYLIST}, FILES, {})

        self.assertEqual(result["undeployed"], ["playlists", "assets"])
        self.assertEqual(result["deployed"], audit.digest(GROUP["deployedPlaylists"]))

    def test_a_group_that_was_never_deployed_is_expected_by_what_it_is_set_to(self):
        group = {"name": "G", "playlists": [{"name": "P"}], "assets": []}

        result = audit.expected_audit(group, {}, [], {})

        self.assertEqual(result["deployed"], audit.digest([{"name": "P", "settings": {}}]))
        self.assertEqual(result["undeployed"], [])

    def test_an_entry_without_settings_is_the_same_as_one_with_empty_settings_like_the_player_has_it(self):
        group = {"name": "G", "deployedPlaylists": [{"name": "TV_OFF", "plType": "special"}]}
        folders_report = {"deployed": audit.digest([{"name": "TV_OFF", "plType": "special", "settings": {}}])}

        result = audit.compare_audit(audit.expected_audit(group, {}, [], {}), {"files": {}, **folders_report})

        self.assertFalse(result["different"]["deployed"])

    def test_no_validity_is_the_same_as_an_empty_one(self):
        self.assertEqual(audit.expected_audit({"name": "G"}, {}, [], {})["validity"], audit.digest([]))

    def test_a_playlist_the_server_does_not_know_is_not_judged(self):
        result = audit.expected_audit(GROUP, {}, FILES, {})

        self.assertEqual(result["playlists"], {})


class SizeTest(unittest.TestCase):
    def test_the_size_is_read_as_the_server_writes_it_with_the_room_its_rounding_leaves(self):
        self.assertEqual(audit.parse_size("351839B"), (351839, 0))
        self.assertEqual(audit.parse_size("7401KB"), (7401000, 1000))
        self.assertEqual(audit.parse_size("12.3MB"), (12300000, 100000))
        self.assertEqual(audit.parse_size("1.5 GB"), (1500000000, 100000000))
        for text in ("", "x", None, "12 parsecs"):
            self.assertIsNone(audit.parse_size(text))

    def test_the_real_size_of_a_file_rounded_by_the_server_matches(self):
        size, tolerance = audit.parse_size("7401KB")  # 7 401 816 B is what the player has

        self.assertLessEqual(abs(7401816 - size), tolerance + 999)  # the server cuts the KB off, the gap is under a KB

    def test_a_truncated_file_does_not_match(self):
        for server_text, have in (("7401KB", 3000000), ("351839B", 351838), ("12.3MB", 1)):
            with self.subTest(server_text=server_text):
                size, tolerance = audit.parse_size(server_text)
                expectation = {"files": ["a"], "sizes": {"a": (size, tolerance)}, "deployed": "", "validity": "",
                               "settings": {}, "playlists": {}}

                result = audit.compare_audit(expectation, {"files": {"a": have}})

                self.assertEqual(result["wrong_size"], [("a", size, have)])


if __name__ == "__main__":
    unittest.main()
