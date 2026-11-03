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
        return super().load(GroupSettingsProcessor, text, real_text, action="set_group_settings")

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
        for cells in (FULL[:2], FULL[:6], FULL + ["x", "y"]):
            with self.subTest(columns=len(cells)):
                processor, logger = self.load(line(*cells))

                self.assertIn("columns_error", self.messages(logger))
                self.assertTrue(processor.refused)
                self.assertEqual(processor.data, {})

    def test_an_empty_resolution_or_orientation_is_refused_because_it_would_overwrite_the_group(self):
        for index in (1, 2):
            with self.subTest(column=index):
                cells = list(FULL)
                cells[index] = ""
                processor, logger = self.load(line(*cells))

                self.assertTrue(any(key.startswith("cell_error") for key in self.messages(logger)))
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

    def test_the_display_columns_and_the_player_may_be_left_out_at_the_end_of_the_line(self):
        processor, _ = self.load(line(*FULL[:7]))  # the name and 6 values
        self.assertFalse(processor.refused)
        self.assertEqual(processor.data["G1"][6:], ["", "", ""])  # no display schedule, the default video player

        processor, _ = self.load(line(*FULL[:9]))  # both display times, no video player
        self.assertFalse(processor.refused)
        self.assertEqual(processor.data["G1"][6:], ["06:00", "22:00", ""])

    def test_a_display_time_that_is_there_without_the_other_is_still_refused_when_the_line_ends_there(self):
        processor, logger = self.load(line(*FULL[:8]))  # only the time the display is switched on

        self.assertIn("sleep_times_incomplete", self.messages(logger))
        self.assertTrue(processor.refused)

    def test_the_line_of_the_report_without_the_lcd_columns_is_accepted_and_says_what_it_took_as_empty(self):
        cells = ["c10_IND_2BW_L_all", "1080p", "landscape", "", "3:10", "true", "true"]  # what a spreadsheet copies
        self.server.get_group_names.return_value = ["c10_IND_2BW_L_all"]
        processor, logger = self.load(line(*cells), real_text=True)

        self.assertFalse(processor.refused)
        self.assertEqual(processor.data["c10_IND_2BW_L_all"], ["1080p", "landscape", "", "03:10", True, True, "", "", ""])
        self.assertIn("Řádek 1: sloupce 8 (LCD zapnout), 9 (LCD vypnout) na řádku chybí, berou se jako prázdné "
                      "(žádný časovač LCD).", self.messages(logger, "info"))

    def test_a_line_that_lacks_a_value_before_the_display_columns_is_refused_and_says_which_columns(self):
        cells = ["c10_IND_2BW_L_all", "1080p", "landscape", "", "3:10", "true"]  # the play-all flag is missing
        processor, logger = self.load(line(*cells), real_text=True)

        message = self.messages(logger)[0]
        self.assertIn("Řádek 1: špatný počet sloupců: zadáno 6, očekává se 7 až 10", message)
        self.assertIn("Chybí sloupce: 7 (přehrávat všechny vyhovující playlisty)", message)
        self.assertIn("Zadáno: c10_IND_2BW_L_all⇥1080p⇥landscape⇥⇥3:10⇥true", message)
        self.assertTrue(processor.refused)

    def test_a_line_with_spaces_instead_of_tabs_says_so(self):
        processor, logger = self.load("c10 1080p landscape 03:00", real_text=True)

        self.assertIn("Sloupce se oddělují tabulátorem", self.messages(logger)[0])

    def test_too_many_columns_are_counted(self):
        processor, logger = self.load(line(*(FULL + ["x", "y"])), real_text=True)

        self.assertIn("Přebývá sloupců: 2", self.messages(logger)[0])

    def test_a_value_that_is_wrong_says_the_column_what_was_entered_and_what_is_expected(self):
        cells = ["G1", "1080p", "landscape", "abc", "25:00", "tru", "maybe", "06:00", "22:00", "vlc"]
        processor, logger = self.load(line(*cells), real_text=True)

        errors = self.messages(logger)
        self.assertIn("Řádek 1, sloupec 4 (automatický restart): zadáno „abc“, očekává se: čas HH:MM, prázdné = vypnuto.",
                      errors)
        self.assertIn("Řádek 1, sloupec 5 (automatický deploy): zadáno „25:00“, očekává se: čas HH:MM, prázdné = vypnuto.",
                      errors)
        self.assertIn("Řádek 1, sloupec 6 (kombinovat výchozí playlist): zadáno „tru“, očekává se: true / false.", errors)
        self.assertIn("Řádek 1, sloupec 7 (přehrávat všechny vyhovující playlisty): zadáno „maybe“, očekává se: true / "
                      "false.", errors)
        self.assertIn("Řádek 1, sloupec 10 (video přehrávač): zadáno „vlc“, očekává se: default / mpv / cvlc.", errors)
        self.assertTrue(processor.refused)

    def test_an_empty_required_value_is_told_as_empty(self):
        cells = list(FULL)
        cells[1] = ""
        processor, logger = self.load(line(*cells), real_text=True)

        self.assertTrue(any(message.startswith("Řádek 1, sloupec 2 (rozlišení): zadáno „(prázdné)“, očekává se:")
                            for message in self.messages(logger)))

    def test_half_of_the_display_schedule_names_the_columns_and_what_is_filled_in(self):
        processor, logger = self.load(line(*(FULL[:7] + ["06:00", "", "mpv"])), real_text=True)

        self.assertIn("Řádek 1, sloupce 8 a 9 (LCD zapnout a vypnout), skupina \"G1\": vyplněno jen jedno (zapnout: "
                      "06:00, vypnout: (prázdné)); vyplňte obě, nebo ani jedno.", self.messages(logger))

    def test_the_other_ways_to_write_a_true_or_a_false_are_taken(self):
        for text, value in (("TRUE", True), ("1", True), ("yes", True), ("False", False), ("0", False), ("no", False)):
            with self.subTest(text=text):
                processor, _ = self.load(line(*(FULL[:5] + [text, text] + FULL[7:])))

                self.assertEqual(processor.data["G1"][4:6], [value, value])

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

    def reboot(self, iso):
        api = self.make_api()
        api.set_group_settings("G", "1080p", "landscape", iso, None, False, True, None, None, "default")
        return api._make_request.call_args.kwargs["json"]["reboot"]

    def test_the_restart_is_written_with_the_time_as_the_person_sees_it_like_the_web_app_does(self):
        # what the web app stores for 23:00 (checked on the demo account, in summer too): the time and next to it the text
        self.assertEqual(self.reboot("1970-01-01T22:00:00.000Z"),
                         {"enable": True, "time": "1970-01-01T22:00:00.000Z", "absoluteTime": "23:00"})

    def test_the_time_as_the_person_sees_it_goes_past_midnight_and_a_time_that_is_not_one_adds_nothing(self):
        self.assertEqual(self.reboot("1970-01-01T23:30:00.000Z")["absoluteTime"], "00:30")
        self.assertEqual(self.reboot("1970-01-01T00:00:00.000Z")["absoluteTime"], "01:00")
        self.assertNotIn("absoluteTime", self.reboot("not a time"))

    def test_no_restart_is_just_switched_off(self):
        self.assertEqual(self.reboot(None), {"enable": False})

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
