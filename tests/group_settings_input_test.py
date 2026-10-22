"""The table "parameters of the groups" is written to the server as it stands, so a line that is cut short, has a time
that cannot be read or gives only half of the display schedule must be refused instead of switching things off."""
import unittest
from unittest.mock import MagicMock

from api_testing.request_calls import ServerApi
from pasted_playlists_test import ProcessorCase, line
from processor.input_processing import GroupSettingsProcessor

FULL = ["G1", "1080p", "landscape", "03:00", "04:00", "true", "false", "06:00", "22:00", "mpv"]


class GroupSettingsInputTest(ProcessorCase):
    def setUp(self):
        super().setUp()
        self.server.set_group_settings.return_value = {"data": {"name": "G1"}}

    def load(self, text, real_text=False):
        return super().load(GroupSettingsProcessor, text, real_text)

    def test_a_complete_line_is_read_and_sent_with_the_times_in_the_form_the_server_takes(self):
        processor, _ = self.load(line(*FULL))

        self.assertEqual(processor.data["G1"], ["1080p", "landscape", "03:00", "04:00", True, False, "06:00", "22:00",
                                                "mpv"])
        list(processor.run())
        self.server.set_group_settings.assert_called_once_with(
            "G1", "1080p", "landscape", "1970-01-01T02:00:00.000Z", "1970-01-01T03:00:00.000Z", True, False,
            "06:00", "22:00", "mpv")

    def test_times_written_in_the_other_usual_ways_are_normalized_before_they_are_sent(self):
        cells = FULL[:3] + ["3:00:00", "4:00", "true", "true", "6:00", "0:00", "mpv"]
        processor, _ = self.load(line(*cells))

        self.assertEqual(processor.data["G1"][2:4], ["03:00", "04:00"])
        self.assertEqual(processor.data["G1"][6:8], ["06:00", "23:59"])  # an off time of midnight is the end of the day
        list(processor.run())  # a time_to_iso that fails on it ends the batch

    def test_the_last_column_may_be_left_out(self):
        processor, _ = self.load(line(*FULL[:9]))

        self.assertEqual(processor.data["G1"][8], "")

    def test_a_line_with_too_few_or_too_many_columns_is_refused_whole(self):
        for cells in (FULL[:2], FULL[:7], FULL + ["x", "y"]):
            with self.subTest(columns=len(cells)):
                processor, logger = self.load(line(*cells))

                self.assertIn("incorrect_format", self.messages(logger))
                self.assertTrue(processor.refused)
                self.assertEqual(processor.data, {})

    def test_an_empty_resolution_or_orientation_is_refused_because_it_would_overwrite_the_group(self):
        for index in (1, 2):
            with self.subTest(column=index):
                cells = list(FULL)
                cells[index] = ""
                processor, logger = self.load(line(*cells))

                self.assertIn("missing_group_setting", self.messages(logger))
                self.assertTrue(processor.refused)

    def test_a_time_that_cannot_be_read_is_reported_with_its_line_and_does_not_end_the_load(self):
        text = "\n".join([line(*FULL), "", line(*(["G2"] + FULL[1:3] + ["abc", "25:00"] + FULL[5:]))])
        processor, logger = self.load(text, real_text=True)

        errors = self.messages(logger)
        self.assertEqual(sum("Řádek 3" in message and "abc" in message for message in errors), 1)
        self.assertEqual(sum("Řádek 3" in message and "25:00" in message for message in errors), 1)
        self.assertTrue(processor.refused)

    def test_a_display_with_only_one_of_its_two_times_is_refused(self):
        for on, off in (("06:00", ""), ("", "22:00")):
            with self.subTest(on=on, off=off):
                processor, logger = self.load(line(*(FULL[:7] + [on, off, "mpv"])))

                self.assertIn("sleep_times_incomplete", self.messages(logger))
                self.assertTrue(processor.refused)

    def test_a_display_without_any_schedule_is_fine(self):
        processor, _ = self.load(line(*(FULL[:7] + ["", "", "mpv"])))

        self.assertFalse(processor.refused)
        self.assertEqual(processor.data["G1"][6:8], ["", ""])

    def test_the_line_of_an_unknown_group_is_numbered_as_the_user_sees_it(self):
        text = "\n".join([line(*FULL), "", line(*(["Nowhere"] + FULL[1:]))])
        processor, logger = self.load(text, real_text=True)

        self.assertTrue(any("Řádek 3" in message for message in self.messages(logger, "warning")))


class GroupSettingsRequestTest(unittest.TestCase):
    def make_api(self):
        api = ServerApi.__new__(ServerApi)
        api.get_group_id_by_name = MagicMock(return_value="gid")
        api._make_request = MagicMock(return_value={"success": True})
        return api

    def body(self, on_time, off_time):
        api = self.make_api()
        api.set_group_settings("G", "1080p", "landscape", None, None, False, True, on_time, off_time, "default")
        return api._make_request.call_args.kwargs["json"]

    def test_the_display_schedule_is_switched_on_only_when_both_times_are_given(self):
        self.assertEqual(self.body("06:00", "22:00")["sleep"], {"enable": True, "ontime": "06:00", "offtime": "22:00"})
        for on, off in (("06:00", None), (None, "22:00"), (None, None)):
            with self.subTest(on=on, off=off):
                self.assertEqual(self.body(on, off)["sleep"], {"enable": False})

    def test_the_times_of_a_display_schedule_that_is_switched_off_are_not_exported(self):
        api = self.make_api()
        api._make_request.return_value = {"data": [
            {"name": "On", "sleep": {"enable": True, "ontime": "08:30", "offtime": "18:30"}},
            {"name": "Off", "sleep": {"enable": False, "ontime": "08:30", "offtime": "18:30"}},
            {"name": "None", "sleep": {"enable": False}},
            {"name": "NoSleep"}]}

        exported = {row[0]: row[7:9] for row in api.get_group_settings()}

        self.assertEqual(exported, {"On": ("08:30", "18:30"), "Off": (None, None), "None": (None, None),
                                    "NoSleep": (None, None)})


if __name__ == "__main__":
    unittest.main()
