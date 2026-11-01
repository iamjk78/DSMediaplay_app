"""How requests to the server are sent: with a timeout, the token in a header, and errors that never show the token."""
import copy
import re
import unittest
from urllib.parse import quote
from unittest.mock import MagicMock

import requests

from api_testing.request_calls import (REQUEST_TIMEOUT, SNAPSHOT_TIMEOUT, TOKEN_HEADER, NameResolutionError,
                                       ResponseError, ServerApi, label_pattern, without_secrets)

TOKEN = "SECRET-TOKEN-123"


def make_api(status=200, body=None, ok=None):
    api = ServerApi.__new__(ServerApi)
    api._url, api._session_token, api._assert_hostname = "https://x.example.com/api", TOKEN, None
    response = MagicMock()
    response.status_code = status
    response.ok = (200 <= status < 300) if ok is None else ok
    response.json.return_value = {"success": True} if body is None else body
    api._request = MagicMock(return_value=response)
    return api


class TimeoutTest(unittest.TestCase):
    def test_every_request_gets_a_timeout_so_that_none_can_hang_for_good(self):
        api = make_api()

        api._make_request("get", "/players")

        self.assertEqual(api._request.call_args.kwargs["timeout"], REQUEST_TIMEOUT)
        connect, read = REQUEST_TIMEOUT
        self.assertTrue(0 < connect <= 30 and 0 < read <= 120)

    def test_a_timeout_a_caller_asks_for_is_kept(self):
        api = make_api()

        api._make_request("post", "/snapshot/1", timeout=SNAPSHOT_TIMEOUT)

        self.assertEqual(api._request.call_args.kwargs["timeout"], SNAPSHOT_TIMEOUT)

    def test_a_request_that_times_out_raises_instead_of_waiting(self):
        api = make_api()
        api._request.side_effect = requests.exceptions.Timeout()

        with self.assertRaises(requests.exceptions.Timeout):
            api._make_request("get", "/players")


class TokenInHeaderTest(unittest.TestCase):
    def test_the_token_is_sent_in_a_header_and_not_in_the_address(self):
        api = make_api()

        api._make_request("get", "/players", params={"page": 0})

        args, kwargs = api._request.call_args
        self.assertEqual(kwargs["headers"][TOKEN_HEADER], TOKEN)
        self.assertEqual(kwargs["params"], {"page": 0})
        self.assertNotIn(TOKEN, args[1])
        self.assertNotIn("token", kwargs["params"])

    def test_a_request_without_parameters_has_none_and_the_content_type_stays(self):
        api = make_api()

        api._make_request("get", "/players")

        kwargs = api._request.call_args.kwargs
        self.assertFalse(kwargs.get("params"))
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")

    def test_headers_of_the_caller_are_added_to_the_token_not_instead_of_it(self):
        api = make_api()

        api._make_request("get", "/x", headers={"X-Other": "1"})

        headers = api._request.call_args.kwargs["headers"]
        self.assertEqual(headers[TOKEN_HEADER], TOKEN)
        self.assertEqual(headers["X-Other"], "1")


class ErrorTextTest(unittest.TestCase):
    def assert_without_token(self, error):
        for text in (str(error), repr(error), " ".join(map(str, error.args)), str(error.params)):
            self.assertNotIn(TOKEN, text)

    def test_a_refusal_says_what_was_refused_and_never_shows_the_token(self):
        api = make_api(status=403, ok=False)

        with self.assertRaises(ResponseError) as raised:
            api._make_request("delete", "/groups/5", json={"token": TOKEN})

        error = raised.exception
        self.assert_without_token(error)
        self.assertIn("HTTP 403", str(error))
        self.assertIn("DELETE /groups/5", str(error))
        self.assertEqual(error.status, 403)

    def test_an_answer_that_says_it_failed_carries_the_servers_message(self):
        api = make_api(body={"success": False, "stat_message": "Player is offline"})

        with self.assertRaises(ResponseError) as raised:
            api._make_request("post", "/snapshot/1")

        self.assertIn("Player is offline", str(raised.exception))
        self.assert_without_token(raised.exception)

    def test_an_error_built_from_request_parameters_with_a_token_hides_it(self):
        for params in ({"token": TOKEN}, {"headers": {"X-Access-Token": TOKEN}}, {"json": {"password": TOKEN}}):
            with self.subTest(params=params):
                self.assert_without_token(ResponseError(params))

    def test_without_secrets_removes_them_at_any_depth_without_touching_the_original(self):
        original = {"params": {"token": TOKEN, "page": 1}, "headers": {"x-access-token": TOKEN, "A": "b"},
                    "json": {"password": "p", "name": "n"}}

        cleaned = without_secrets(original)

        self.assertEqual(cleaned, {"params": {"page": 1}, "headers": {"A": "b"}, "json": {"name": "n"}})
        self.assertEqual(original["params"]["token"], TOKEN)

    def test_an_error_without_details_still_reads_well(self):
        self.assertEqual(str(ResponseError({})), "The server refused the request")


class PlayAllEligibleTest(unittest.TestCase):
    """The group setting "play all eligible playlists" is sent on purpose: the CMS depends on it."""

    def make_api(self):
        api = ServerApi.__new__(ServerApi)
        api.get_group_id_by_name = MagicMock(return_value="gid")
        api.get_group_details = MagicMock(return_value={"playlists": []})
        api._make_request = MagicMock(return_value={"success": True})
        return api

    def test_every_way_of_writing_the_playlists_of_a_group_plays_all_eligible_ones(self):
        writers = {
            "set_playlist_to_group": lambda api: api.set_playlist_to_group("G", [("P", None, None, None, None)]),
            "set_playlist_to_group_detailed": lambda api: api.set_playlist_to_group_detailed(
                "G", [("P", None, None, None, None, None)]),
        }
        for name, write in writers.items():
            with self.subTest(writer=name):
                api = self.make_api()

                write(api)

                body = api._make_request.call_args.kwargs["json"]
                self.assertEqual(body["playAllEligiblePlaylists"], "true")


# What the demo server holds in a group (shapes copied from its answers): the types of the playlists, "skip for
# schedule", ads, audio and dominance are all things the tables and the CSV know nothing about.
TV_OFF = {"name": "TV_OFF", "plType": "special", "skipForSchedule": False}
PROMO = {"name": "Promo", "plType": "regular", "skipForSchedule": True,
         "settings": {"weekdays": [1, 2], "timeEnable": "true", "starttime": "00:00", "endtime": "07:30",
                      "ads": {"adPlaylist": False, "adCount": 1, "adInterval": 60},
                      "audio": {"enable": False, "random": False, "volume": 50},
                      "domination": {"enable": True, "timeInterval": 48}, "monthdays": [1, 15]}}
SWITCHED_OFF = {"name": "Off", "plType": "regular", "skipForSchedule": False,
                "settings": {"durationEnable": False, "startdate": None, "enddate": None, "timeEnable": False,
                             "ads": {"adPlaylist": False, "adCount": 1, "adInterval": 60}}}


class KeepWhatTheGroupHasTest(unittest.TestCase):
    """Writing the playlists of a group from a table used to throw away every setting the table does not show."""

    def make_api(self, playlists):
        api = ServerApi.__new__(ServerApi)
        api.get_group_id_by_name = MagicMock(return_value="gid")
        api.get_group_details = MagicMock(return_value={"playlists": copy.deepcopy(playlists)})
        api._make_request = MagicMock(return_value={"success": True})
        return api

    @staticmethod
    def sent(api):
        return api._make_request.call_args.kwargs["json"]["playlists"]

    def test_playlists_the_table_does_not_change_are_sent_back_exactly_as_the_group_has_them(self):
        api = self.make_api([TV_OFF, PROMO, SWITCHED_OFF])

        api.set_playlist_to_group_detailed("G", [
            ("TV_OFF", None, None, None, None, None),
            ("Promo", None, None, [1, 2], "00:00", "07:30"),
            ("Off", None, None, None, None, None)])

        self.assertEqual(self.sent(api), [TV_OFF, PROMO, SWITCHED_OFF])

    def test_a_changed_schedule_replaces_only_the_schedule(self):
        api = self.make_api([PROMO])

        api.set_playlist_to_group_detailed("G", [("Promo", None, None, [3], "08:00", "09:00")])

        (sent,) = self.sent(api)
        self.assertEqual(sent["settings"]["weekdays"], [3])
        self.assertEqual((sent["settings"]["starttime"], sent["settings"]["endtime"]), ("08:00", "09:00"))
        for kept in ("ads", "audio", "domination", "monthdays"):
            self.assertEqual(sent["settings"][kept], PROMO["settings"][kept])
        self.assertEqual((sent["plType"], sent["skipForSchedule"]), ("regular", True))

    def test_a_restriction_the_table_leaves_empty_is_removed_the_others_stay(self):
        api = self.make_api([PROMO])

        api.set_playlist_to_group_detailed("G", [("Promo", None, None, None, None, None)])

        (sent,) = self.sent(api)
        for removed in ("weekdays", "timeEnable", "starttime", "endtime"):
            self.assertNotIn(removed, sent["settings"])
        self.assertEqual(sent["settings"]["domination"], PROMO["settings"]["domination"])

    def test_switching_a_restriction_on_that_the_group_has_but_switched_off_does_switch_it_on(self):
        leftover = {"name": "Off", "settings": {"durationEnable": False, "startdate": "2026-01-01", "enddate": "2026-02-01",
                                                  "audio": {"enable": False}}}
        api = self.make_api([leftover])

        api.set_playlist_to_group_detailed("G", [("Off", "2026-01-01", "2026-02-01", None, None, None)])

        (sent,) = self.sent(api)
        self.assertEqual(sent["settings"]["durationEnable"], "true")
        self.assertEqual(sent["settings"]["audio"], {"enable": False})

    def test_a_new_playlist_is_written_from_the_table_and_the_same_name_twice_is_matched_in_order(self):
        second = {**PROMO, "skipForSchedule": False}
        api = self.make_api([PROMO, second])

        api.set_playlist_to_group_detailed("G", [
            ("Promo", None, None, [1, 2], "00:00", "07:30"),
            ("Promo", None, None, [1, 2], "00:00", "07:30"),
            ("New", "2026-01-01", None, None, None, None)])

        first_sent, second_sent, new = self.sent(api)
        self.assertTrue(first_sent["skipForSchedule"])
        self.assertFalse(second_sent["skipForSchedule"])
        self.assertEqual(new, {"name": "New", "settings": {"durationEnable": "true", "startdate": "2026-01-01"}})

    def test_the_older_writer_without_days_of_the_week_keeps_them_too(self):
        api = self.make_api([PROMO])

        api.set_playlist_to_group("G", [("Promo", "2026-01-01", "2026-02-01", "08:00", "09:00")])

        (sent,) = self.sent(api)
        self.assertEqual(sent["settings"]["weekdays"], [1, 2])
        self.assertEqual(sent["settings"]["startdate"], "2026-01-01")
        self.assertEqual(sent["settings"]["domination"], PROMO["settings"]["domination"])
        self.assertEqual(api._make_request.call_args.kwargs["json"]["playAllEligiblePlaylists"], "true")

    def test_removing_a_playlist_leaves_the_others_untouched_and_play_all_on(self):
        api = ServerApi.__new__(ServerApi)
        api._make_request = MagicMock(side_effect=[
            {"data": [{"_id": "g1", "name": "G1", "playlists": copy.deepcopy([TV_OFF, PROMO, SWITCHED_OFF])},
                      {"_id": "g2", "name": "G2", "playlists": [copy.deepcopy(TV_OFF)]}]},
            {"data": []},  # the playlists of the account (needed for the files of the group; none known here)
            {"success": True}])

        removed = api.remove_playlists_from_groups(["Promo"])

        self.assertEqual(removed, {"G1": ["Promo"]})
        self.assertEqual(api._make_request.call_count, 3)  # the groups, the playlists, one write: G2 is not written at all
        method, endpoint = api._make_request.call_args.args
        body = api._make_request.call_args.kwargs["json"]
        self.assertEqual((method, endpoint), ("post", "/groups/g1"))
        self.assertEqual(body["playlists"], [TV_OFF, SWITCHED_OFF])
        self.assertEqual(body["playAllEligiblePlaylists"], "true")
        self.assertEqual(body["assets"], [])  # the files of the group are sent with its playlists (see group_files_test)


class NamesInRequestsTest(unittest.TestCase):
    """A name is part of the path of a request or the word a search is made with, and it is any text a user chose."""

    NAMES = ["a?b.mp4", "Menu #2.jpg", "100%.jpg", "100%25.jpg", "a/b", "plain name.mp4"]

    def make_api(self, data=None):
        api = ServerApi.__new__(ServerApi)
        api._make_request = MagicMock(return_value={"success": True, "data": data})
        return api

    def test_a_name_is_one_part_of_the_path_whatever_it_contains(self):
        for name in self.NAMES:
            with self.subTest(name=name):
                api = self.make_api({"dbdata": {"_id": "x"}})
                api.delete_asset(name)
                path = api._make_request.call_args.args[1]
                self.assertEqual(path, "/files/" + quote(name, safe=""))
                self.assertNotIn("?", path)
                self.assertNotIn("#", path)
                self.assertEqual(path.count("/"), 2)

                api = self.make_api()
                api.delete_playlist(name)
                self.assertEqual(api._make_request.call_args_list[0].args[1], "/files/" + quote(f"__{name}.json", safe=""))

                api = self.make_api({"dbdata": {"_id": "x"}})
                api.get_asset_id_by_name(name)
                self.assertEqual(api._make_request.call_args.args[1], "/files/" + quote(name, safe=""))

    def test_the_search_of_a_label_takes_the_name_literally(self):
        for name in ("TV (old)", "a.b", "x[1]", "1+1", "50%", "plain"):
            with self.subTest(name=name):
                self.assertTrue(re.fullmatch(label_pattern(name), name))
        self.assertFalse(re.fullmatch(label_pattern("a.b"), "axb"))

    def test_a_group_or_label_is_found_only_by_its_own_name(self):
        found = [{"_id": "1", "name": "Shop 1"}]  # what a search for "Shop" gives
        for lookup in ("get_group_id_by_name", "get_label_id_by_name"):
            with self.subTest(lookup=lookup):
                api = self.make_api(found)

                with self.assertRaises(NameResolutionError):
                    getattr(api, lookup)("Shop")
                self.assertEqual(getattr(api, lookup)("Shop 1"), "1")

    def test_two_groups_with_the_same_name_are_not_guessed_between(self):
        api = self.make_api([{"_id": "1", "name": "Shop"}, {"_id": "2", "name": "Shop"}])

        with self.assertRaises(NameResolutionError):
            api.get_group_id_by_name("Shop")

    def test_the_search_of_labels_is_sent_escaped(self):
        api = self.make_api([{"_id": "1", "name": "TV (old)"}])

        self.assertEqual(api.get_label_id_by_name("TV (old)"), "1")
        self.assertEqual(api._make_request.call_args.kwargs["params"], {"string": "TV \\(old\\)"})

    def test_a_label_without_a_name_is_nobodys_to_delete(self):
        api = self.make_api([{"_id": "1", "name": "left"}, {"_id": "2"}, {"_id": "3", "name": ""}])

        self.assertEqual(api.get_labels(), ["left"])

    def test_answers_with_null_where_a_list_belongs_do_not_stop_the_reading(self):
        api = self.make_api([{"configLocation": "L1", "toggleRows": None},
                             {"configLocation": "L2", "toggleRows": [{"weekDays": [True], "turnOn": None}]}])

        locations = api.get_locations()

        self.assertEqual([next(iter(location)) for location in locations], ["L1", "L2"])
        api = self.make_api([{"name": "G", "playlists": None}])
        self.assertEqual(api.get_groups_playlists_details(), {"G": []})


class KeepWhatThePlaylistHasTest(unittest.TestCase):
    """Taking one asset out of a playlist used to write all the others from their names alone, which reset the durations
    they are shown for (and the zones and full screen) to the defaults."""

    SHORT = {"filename": "a.jpg", "duration": 33, "selected": True, "option": {"main": False}, "dragSelected": True,
             "fullscreen": True, "isVideo": False}
    LONG = {"filename": "b.mp4", "duration": 7, "selected": True, "option": {"main": False}, "isVideo": True,
            "dragSelected": True}

    def make_api(self, assets):
        api = ServerApi.__new__(ServerApi)
        written = []

        def request(method, endpoint, **kwargs):
            if method == "get":
                return {"success": True, "data": {"name": "P", "assets": copy.deepcopy(assets)}}
            written.append((endpoint, kwargs["json"]))
            return {"success": True}

        api._make_request = MagicMock(side_effect=request)
        api.written = written
        return api

    def sent(self, api):
        return dict(api.written)["/playlists/P"]["assets"]

    def test_the_assets_that_stay_are_sent_back_as_the_playlist_has_them(self):
        api = self.make_api([self.SHORT, self.LONG, {"filename": "c.jpg"}])

        api.set_assets_to_playlist("P", ["a.jpg", "b.mp4"])

        self.assertEqual(self.sent(api), [self.SHORT, self.LONG])

    def test_a_new_asset_gets_the_defaults_and_the_order_is_the_one_asked_for(self):
        api = self.make_api([self.SHORT, self.LONG])

        api.set_assets_to_playlist("P", ["b.mp4", "new.jpg", "a.jpg"])

        sent = self.sent(api)
        self.assertEqual([asset["filename"] for asset in sent], ["b.mp4", "new.jpg", "a.jpg"])
        self.assertEqual(sent[0], self.LONG)
        self.assertEqual(sent[1], {"filename": "new.jpg", "selected": "true", "dragSelected": "true",
                                   "option": {"main": "true"}})
        self.assertEqual(sent[2], self.SHORT)

    def test_an_asset_listed_twice_keeps_its_settings_once(self):
        api = self.make_api([self.SHORT])

        api.set_assets_to_playlist("P", ["a.jpg", "a.jpg"])

        first, second = self.sent(api)
        self.assertEqual(first, self.SHORT)
        self.assertNotIn("duration", second)

    def test_the_files_are_set_before_the_playlist_is_written_and_a_refusal_stops_it(self):
        class Refusal(dict):
            status_code = None

        api = ServerApi.__new__(ServerApi)
        api._make_request = MagicMock(side_effect=lambda method, endpoint, **kw: (
            {"success": True, "data": {"assets": [self.SHORT]}} if method == "get" else Refusal(success=False)))

        result = api.set_assets_to_playlist("P", ["a.jpg"])

        self.assertEqual(result.status_code, 400)
        self.assertEqual([call.args[1] for call in api._make_request.call_args_list], ["/playlists/P", "/playlistfiles"])


class PlaylistSettingsRequestTest(unittest.TestCase):
    """The domination of a playlist is one of its settings; the server takes the whole settings object as sent."""

    ADS = {"adPlaylist": True, "adCount": 3, "adInterval": 15}

    def make_api(self, settings):
        api = ServerApi.__new__(ServerApi)
        api._make_request = MagicMock(side_effect=lambda method, endpoint, **kw: {
            "success": True, "data": {"name": "P", "settings": copy.deepcopy(settings)}})
        return api

    def sent(self, api):
        return api._make_request.call_args.kwargs["json"]["settings"]

    def test_switching_the_domination_on_keeps_the_other_settings(self):
        api = self.make_api({"ads": self.ADS, "audio": {"enable": True}})

        api.set_playlist_settings("P", "300")

        self.assertEqual(self.sent(api), {"ads": self.ADS, "audio": {"enable": True},
                                          "domination": {"enable": True, "timeInterval": 300}})

    def test_switching_it_off_keeps_the_other_settings_and_drops_the_interval(self):
        api = self.make_api({"ads": self.ADS, "domination": {"enable": True, "timeInterval": 300}})

        api.set_playlist_settings("P", "")

        self.assertEqual(self.sent(api), {"ads": self.ADS, "domination": {"enable": False}})

    def test_what_the_domination_has_besides_the_interval_stays_when_it_is_switched_on(self):
        api = self.make_api({"domination": {"enable": False, "timeInterval": 10, "startOnly": True}})

        api.set_playlist_settings("P", "300")

        self.assertEqual(self.sent(api), {"domination": {"enable": True, "timeInterval": 300, "startOnly": True}})

    def test_a_playlist_without_settings_gets_only_the_domination(self):
        api = self.make_api(None)

        api.set_playlist_settings("P", "60")

        self.assertEqual(self.sent(api), {"domination": {"enable": True, "timeInterval": 60}})


class PlayerIdsAreReadOnceTest(unittest.TestCase):
    """An action for 500 players used to ask for the list of all 500 players for every one of them."""

    def make_api(self, listing):
        api = ServerApi.__new__(ServerApi)
        api.get_player_objects = MagicMock(side_effect=lambda: copy.deepcopy(listing))
        api._make_request = MagicMock(return_value={"data": {}})
        return api

    def test_many_lookups_read_the_players_once(self):
        listing = [{"name": f"P{i}", "_id": f"id{i}"} for i in range(50)]
        api = self.make_api(listing)

        ids = [api.get_player_id_by_name(f"P{i}") for i in range(50)]

        self.assertEqual(ids, [f"id{i}" for i in range(50)])
        api.get_player_objects.assert_called_once()

    def test_an_unknown_name_gets_one_more_look_before_it_is_refused(self):
        api = self.make_api([{"name": "A", "_id": "1"}])
        api.get_player_id_by_name("A")

        with self.assertRaises(NameResolutionError):
            api.get_player_id_by_name("Typo")

        self.assertEqual(api.get_player_objects.call_count, 2)

    def test_a_player_made_in_the_meantime_is_found_by_that_look(self):
        listing = [{"name": "A", "_id": "1"}]
        api = self.make_api(listing)
        api.get_player_id_by_name("A")
        listing.append({"name": "New", "_id": "2"})

        self.assertEqual(api.get_player_id_by_name("New"), "2")

    def test_of_two_players_with_one_name_the_first_counts_as_before(self):
        api = self.make_api([{"name": "Twin", "_id": "first"}, {"name": "Twin", "_id": "second"}])

        self.assertEqual(api.get_player_id_by_name("Twin"), "first")

    def test_after_a_rename_the_old_name_is_not_found_any_more(self):
        listing = [{"name": "Old", "_id": "1"}]
        api = self.make_api(listing)
        api.get_player_id_by_name("Old")

        api.rename_player("Old", "Renamed")
        listing[0]["name"] = "Renamed"

        with self.assertRaises(NameResolutionError):
            api.get_player_id_by_name("Old")  # a name read before the rename would still give the id
        self.assertEqual(api.get_player_id_by_name("Renamed"), "1")

    def test_creating_a_player_makes_the_names_be_read_again(self):
        listing = [{"name": "A", "_id": "1"}]
        api = self.make_api(listing)
        api.get_player_id_by_name("A")

        api.create_player("B")

        self.assertIsNone(api._player_ids)


if __name__ == "__main__":
    unittest.main()
