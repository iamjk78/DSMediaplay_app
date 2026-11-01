"""A playlist of a group that is given no times gets the whole day: from 00:00 to 23:59. It holds for the setting of the
playlists of groups and for adding them; the default playlist (it has no restriction by what it is) and the playlists a
group has already are left as they are."""
import unittest
from unittest.mock import MagicMock

from api_testing.request_calls import ServerApi
from pasted_playlists_test import ProcessorCase, line
from processor.input_processing import (WHOLE_DAY_FROM, WHOLE_DAY_TO, AddDetailedPlaylistProcessor,
                                        DetailedPlaylistProcessor)


def block(name="Promo", date_from="", date_to="", days="", time_from="", time_to=""):
    return name, date_from, date_to, days, time_from, time_to


class SettingTest(ProcessorCase):
    def times(self, time_from, time_to, **kwargs):
        processor, _ = self.load(DetailedPlaylistProcessor, line("G1", "", *block(time_from=time_from, time_to=time_to)))
        self.assertFalse(processor.refused, kwargs)
        playlist = processor.data["G1"][0]
        return playlist[4], playlist[5]

    def test_the_constants_are_the_whole_day(self):
        self.assertEqual((WHOLE_DAY_FROM, WHOLE_DAY_TO), ("00:00", "23:59"))

    def test_with_no_times_the_whole_day_is_set(self):
        self.assertEqual(self.times("", ""), ("00:00", "23:59"))

    def test_with_only_one_time_the_other_is_the_edge_of_the_day(self):
        self.assertEqual(self.times("08:00", ""), ("08:00", "23:59"))
        self.assertEqual(self.times("", "18:00"), ("00:00", "18:00"))

    def test_times_that_are_given_are_kept(self):
        self.assertEqual(self.times("08:00", "18:00"), ("08:00", "18:00"))
        self.assertEqual(self.times("8:00", "7:30:00" if False else "18:05"), ("08:00", "18:05"))

    def test_midnight_as_the_end_is_still_the_end_of_the_day(self):
        self.assertEqual(self.times("08:00", "0:00"), ("08:00", "23:59"))

    def test_a_start_that_leaves_no_room_for_the_default_end_is_an_error_not_a_silent_change(self):
        processor, logger = self.load(DetailedPlaylistProcessor, line("G1", "", *block(time_from="23:59")))

        self.assertTrue(processor.refused)
        self.assertTrue(logger.error.called)

    def test_the_other_columns_are_not_touched(self):
        processor, _ = self.load(DetailedPlaylistProcessor,
                                 line("G1", "", *block(date_from="01.01.2026", date_to="31.12.2026", days="mo,tu")))

        name, start, end, weekdays, time_from, time_to = processor.data["G1"][0]
        self.assertEqual((name, start, end, weekdays), ("Promo", "2026-01-01T00:00:00.000Z", "2026-12-31T00:00:00.000Z", [2, 3]))
        self.assertEqual((time_from, time_to), ("00:00", "23:59"))

    def test_every_block_of_a_line_gets_its_own_times(self):
        processor, _ = self.load(DetailedPlaylistProcessor,
                                 line("G1", "", *block("Promo"), *block("Night", time_from="22:00", time_to="06:00" if False else "23:30")))

        self.assertEqual([(p[0], p[4], p[5]) for p in processor.data["G1"]],
                         [("Promo", "00:00", "23:59"), ("Night", "22:00", "23:30")])

    def test_the_default_playlist_stays_without_any_restriction(self):
        processor, _ = self.load(DetailedPlaylistProcessor, line("G1", "Default", *block()))

        self.assertEqual(processor.data["G1"][0], ("Default", None, None, None, None, None))
        self.assertEqual(processor.data["G1"][1][4:], ("00:00", "23:59"))


class AddingTest(ProcessorCase):
    EXISTING = [{"playlist_name": "Night", "start_date": None, "end_date": None, "days_of_week": None,
                 "start_time": "", "end_time": ""},
                {"playlist_name": "Default", "start_date": None, "end_date": None, "days_of_week": None,
                 "start_time": "08:00", "end_time": "12:00"}]

    def adding(self, text):
        self.server.get_groups_playlists_details.return_value = {"G1": [dict(item) for item in self.EXISTING]}
        return self.load(AddingTest.processor_class, text)

    processor_class = AddDetailedPlaylistProcessor

    def test_a_playlist_that_is_added_without_times_gets_the_whole_day(self):
        processor, _ = self.adding(line("G1", *block()))

        self.assertFalse(processor.refused)
        self.assertEqual(processor.data["G1"][-1][0], "Promo")
        self.assertEqual(processor.data["G1"][-1][4:], ("00:00", "23:59"))

    def test_one_missing_time_is_filled_in_the_same_way(self):
        for time_from, time_to, expected in (("09:00", "", ("09:00", "23:59")), ("", "17:00", ("00:00", "17:00"))):
            with self.subTest(time_from=time_from, time_to=time_to):
                processor, _ = self.adding(line("G1", *block(time_from=time_from, time_to=time_to)))
                self.assertEqual(processor.data["G1"][-1][4:], expected)

    def test_what_the_group_has_already_is_kept_as_it_is(self):
        processor, _ = self.adding(line("G1", *block()))

        existing = processor.data["G1"][:-1]
        self.assertEqual([(p[0], p[4], p[5]) for p in existing], [("Night", "", ""), ("Default", "08:00", "12:00")])


class WhatTheServerGetsTest(unittest.TestCase):
    def sent(self, playlists):
        api = ServerApi.__new__(ServerApi)
        api.get_group_id_by_name = MagicMock(return_value="id1")
        api.get_group_details = MagicMock(return_value={})
        api._keep_what_the_group_has = MagicMock(side_effect=lambda group_id, written, managed, details=None: written)
        api._set_group_playlists = MagicMock(return_value={"success": True})
        api.set_playlist_to_group_detailed("G1", playlists)
        return api._keep_what_the_group_has.call_args.args[1][0][0]["settings"]

    def test_the_whole_day_is_a_time_restriction_that_is_switched_on(self):
        settings = self.sent([("Promo", None, None, None, WHOLE_DAY_FROM, WHOLE_DAY_TO)])

        self.assertEqual((settings["timeEnable"], settings["starttime"], settings["endtime"]), ("true", "00:00", "23:59"))

    def test_the_default_playlist_without_times_has_no_time_restriction(self):
        settings = self.sent([("Default", None, None, None, None, None)])

        self.assertNotIn("timeEnable", settings)


if __name__ == "__main__":
    unittest.main()
