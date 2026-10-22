"""How requests to the server are sent: with a timeout, the token in a header, and errors that never show the token."""
import copy
import unittest
from unittest.mock import MagicMock

import requests

from api_testing.request_calls import (REQUEST_TIMEOUT, SNAPSHOT_TIMEOUT, TOKEN_HEADER, ResponseError, ServerApi,
                                       without_secrets)

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
            {"success": True}])

        removed = api.remove_playlists_from_groups(["Promo"])

        self.assertEqual(removed, {"G1": ["Promo"]})
        self.assertEqual(api._make_request.call_count, 2)  # the group without it is not written at all
        method, endpoint = api._make_request.call_args.args
        body = api._make_request.call_args.kwargs["json"]
        self.assertEqual((method, endpoint), ("post", "/groups/g1"))
        self.assertEqual(body["playlists"], [TV_OFF, SWITCHED_OFF])
        self.assertEqual(body["playAllEligiblePlaylists"], "true")


if __name__ == "__main__":
    unittest.main()
