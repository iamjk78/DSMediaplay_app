"""Four smaller actions that checked too little: the validity of an asset (the server refuses "08:00" as an hour), the
interval of domination, and the removal of playlists that have run out."""
import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock

from api_testing.request_calls import ServerApi
from pasted_playlists_test import ProcessorCase, line
from processor.input_processing import (AssetToPlaylistProcessor, AssetValidityProcessor, PlaylistSettingsProcessor,
                                        RemoveExpiredPlaylistsProcessor, parse_validity_hour)
from destructive_actions_test import make_processor


class ValidityHourTest(unittest.TestCase):
    def test_whole_hours_are_taken_in_the_usual_ways(self):
        for text, is_end, expected in (("8", False, 8), ("08", False, 8), ("08:00", False, 8), ("0", False, 0),
                                       ("23:00", False, 23), ("", False, None), ("  ", True, None), ("18:00", True, 18),
                                       ("24", True, 24), ("00:00", True, 24), ("0", True, 24), ("1", True, 1)):
            with self.subTest(text=text, is_end=is_end):
                self.assertEqual(parse_validity_hour(text, is_end), expected)

    def test_what_the_server_would_refuse_or_misread_is_refused_here(self):
        for text, is_end in (("08:30", False), ("8:5", False), ("24", False), ("25", True), ("-1", False), ("ab", False),
                             ("8.00", False), ("٨", False), ("1e1", False)):
            with self.subTest(text=text, is_end=is_end):
                with self.assertRaises(ValueError):
                    parse_validity_hour(text, is_end)


class AssetValidityTest(ProcessorCase):
    def setUp(self):
        super().setUp()
        self.server.get_asset_names.return_value = ["a.jpg", "b.jpg"]
        self.server.set_asset_validity.side_effect = lambda name, *rest: {"data": {"name": name}}

    def load(self, text, real_text=False):
        return super().load(AssetValidityProcessor, text, real_text)

    def test_a_valid_line_is_sent_with_whole_hours_midnight_included(self):
        processor, _ = self.load(line("a.jpg", "01.01.2026", "31.12.2026", "00:00", "24:00") + "\n"
                                 + line("b.jpg", "01.01.2026", "", "8", "18:00"))

        self.assertFalse(processor.refused)
        list(processor.run())
        self.server.set_asset_validity.assert_any_call("a.jpg", "2026-01-01T00:00:00.000Z", "2026-12-31T00:00:00.000Z",
                                                       0, 24)
        self.server.set_asset_validity.assert_any_call("b.jpg", "2026-01-01T00:00:00.000Z", None, 8, 18)

    def test_a_line_with_no_dates_and_no_hours_switches_the_validity_off(self):
        processor, _ = self.load(line("a.jpg"))

        self.assertFalse(processor.refused)
        self.assertEqual(processor.data["a.jpg"], ("", "", None, None))

    def test_a_date_or_hour_that_would_fail_in_the_middle_of_the_batch_is_refused_at_the_load(self):
        for what, cells, key in (
                ("a date in the wrong form", ("a.jpg", "2026-01-01", "", "", ""), "cell_error_plain"),
                ("a date that does not exist", ("a.jpg", "31.02.2026", "", "", ""), "cell_error_plain"),
                ("dates in the wrong order", ("a.jpg", "02.01.2026", "01.01.2026", "", ""), "order_error_date"),
                ("minutes", ("a.jpg", "01.01.2026", "", "8:30", ""), "cell_error_plain"),
                ("an hour of the day that is not one", ("a.jpg", "01.01.2026", "", "", "25"), "cell_error_plain")):
            with self.subTest(what):
                processor, logger = self.load(line(*cells))

                self.assertIn(key, self.messages(logger))
                self.assertTrue(processor.refused)
                self.assertEqual(processor.data, {})

    def test_the_line_is_numbered_as_the_user_sees_it(self):
        text = "\n".join([line("a.jpg"), "", line("b.jpg", "bad")])
        processor, logger = self.load(text, real_text=True)

        self.assertTrue(any("Řádek 3" in message and "bad" in message for message in self.messages(logger)))


class AssetsToPlaylistInputTest(ProcessorCase):
    def setUp(self):
        super().setUp()
        self.server.get_asset_names.return_value = ["a.jpg", "b.jpg"]

    def test_assets_that_exist_are_listed_for_the_playlist(self):
        processor, _ = self.load(AssetToPlaylistProcessor, line("Promo", "a.jpg", "b.jpg"))

        self.assertFalse(processor.refused)
        self.assertEqual(processor.data, {"Promo": ["a.jpg", "b.jpg"]})

    def test_a_misspelt_asset_is_refused_instead_of_putting_a_file_that_is_not_there_into_the_playlist(self):
        processor, logger = self.load(AssetToPlaylistProcessor, line("Promo", "a.jpg", "b.jgp"), real_text=True)

        self.assertTrue(processor.refused)
        self.assertTrue(any("b.jgp" in message for message in self.messages(logger, "warning")))

    def test_the_line_is_numbered_as_the_user_sees_it(self):
        processor, logger = self.load(AssetToPlaylistProcessor, line("Promo", "a.jpg") + "\n\n" + line("Promo", "x"),
                                      real_text=True)

        self.assertTrue(any("Řádek 3" in message for message in self.messages(logger, "warning")))


class AssetValidityRequestTest(unittest.TestCase):
    def test_hour_zero_is_sent_too(self):
        api = ServerApi.__new__(ServerApi)
        api.get_asset_id_by_name = MagicMock(return_value="id")
        api._make_request = MagicMock(return_value={"success": True})

        api.set_asset_validity("a.jpg", "2026-01-01T00:00:00.000Z", None, 0, 24)

        validity = api._make_request.call_args.kwargs["json"]["dbdata"]["validity"]
        self.assertEqual((validity["starthour"], validity["endhour"]), (0, 24))


class DominationIntervalTest(ProcessorCase):
    def setUp(self):
        super().setUp()
        self.server.get_playlist_names.return_value = ["P"]

    def test_a_whole_positive_number_or_nothing_is_taken(self):
        for value in ("300", " 60 ", "1", ""):
            with self.subTest(value=value):
                processor, _ = self.load(PlaylistSettingsProcessor, line("P", value))

                self.assertFalse(processor.refused)
                self.assertEqual(processor.data["P"], value.strip())

    def test_anything_else_is_refused_before_the_batch_starts(self):
        for value in ("abc", "-5", "0", "3.5", "1,5", "٣", "1e3"):
            with self.subTest(value=value):
                processor, logger = self.load(PlaylistSettingsProcessor, line("P", value))

                self.assertIn("cell_error_plain", self.messages(logger))
                self.assertTrue(processor.refused)


class RemoveExpiredTest(unittest.TestCase):
    def run_for(self, removed=None, error=None):
        server = MagicMock()
        if error:
            server.remove_expired_playlists_from_group.side_effect = error
        else:
            server.remove_expired_playlists_from_group.return_value = removed
        processor, logger, patcher = make_processor(RemoveExpiredPlaylistsProcessor, server)
        self.addCleanup(patcher.stop)
        processor._remove_entity(server, "G1")
        return logger

    def test_it_says_which_playlists_were_taken_out_of_the_group_not_that_the_group_was_deleted(self):
        logger = self.run_for(["P1", "P2"])

        logger.info.assert_called_once_with("success_remove_expired")

    def test_a_group_with_nothing_expired_says_so(self):
        logger = self.run_for([])

        logger.info.assert_called_once_with("nothing_expired")

    def test_a_failure_is_reported_and_does_not_end_the_batch(self):
        logger = self.run_for(error=RuntimeError("boom"))

        logger.error.assert_called_once()
        logger.info.assert_not_called()

    def test_the_values_are_given_to_the_message(self):
        server = MagicMock()
        server.remove_expired_playlists_from_group.return_value = ["P1", "P2"]
        processor, logger, patcher = make_processor(RemoveExpiredPlaylistsProcessor, server)
        self.addCleanup(patcher.stop)
        processor.lang.get_message.side_effect = lambda key, **values: f"{key}:{values}"

        processor._remove_entity(server, "G1")

        self.assertIn("'removed': 'P1, P2'", logger.info.call_args.args[0])
        self.assertIn("'group': 'G1'", logger.info.call_args.args[0])


class ExpiredPlaylistsTest(unittest.TestCase):
    def removed(self, playlists):
        api = ServerApi.__new__(ServerApi)
        api.get_group_id_by_name = MagicMock(return_value="gid")
        api.get_group_details = MagicMock(return_value={"playlists": playlists})
        api._set_group_playlists = MagicMock()
        return api.remove_expired_playlists_from_group("G"), api._set_group_playlists

    @staticmethod
    def playlist(name, end_offset_days, switched="true"):
        end = (date.today() + timedelta(days=end_offset_days)).isoformat() + "T00:00:00.000Z"
        return {"name": name, "settings": {"durationEnable": switched, "startdate": "2020-01-01T00:00:00.000Z",
                                           "enddate": end}}

    def test_only_a_playlist_whose_date_restriction_is_on_and_has_passed_is_removed(self):
        playlists = [self.playlist("past", -1), self.playlist("last day", 0), self.playlist("future", 3),
                     self.playlist("past but off", -30, switched=False), self.playlist("past off text", -30, "false"),
                     self.playlist("past on bool", -1, switched=True),
                     {"name": "no settings"}, {"name": "null settings", "settings": None},
                     {"name": "no end", "settings": {"durationEnable": "true"}}]

        removed, update = self.removed(playlists)

        self.assertEqual(removed, ["past", "past on bool"])
        sent = update.call_args.args[2]  # (group id, group name, playlists left, the group as it was)
        self.assertEqual([p["name"] for p in sent], [p["name"] for p in playlists if p["name"] not in removed])

    def test_nothing_is_written_when_nothing_has_expired(self):
        removed, update = self.removed([self.playlist("future", 3)])

        self.assertEqual(removed, [])
        update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
