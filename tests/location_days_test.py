import csv
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from api_testing.request_calls import WEEK_DAYS, ServerApi
from processor.csv_generator import CSVTaskFactory
from processor.input_processing import LocationTimesProcessor
from util.input_templates import template_lines

# What the DSMediaplay web UI shows for the test location "test_casu_lokace" (checked by hand in the browser):
# Sunday 06:00-22:00, Monday 07:00-22:00, ... Saturday 12:00-22:00, one row per day, in the order SU MO TU WE TH FR SA.
UI_ROWS = [{"turnOn": f"{6 + day:02d}:00", "turnOff": "22:00", "weekDays": [index == day for index in range(7)]}
           for day in range(7)]
UI_TIMES = {day: {"on": f"{6 + index:02d}:00", "off": "22:00"} for index, day in enumerate(WEEK_DAYS)}
# The row the app's own CSV export produced for that location; it matches the UI.
EXPORTED_ROW = "test_casu_lokace;06:00;22:00;07:00;22:00;08:00;22:00;09:00;22:00;10:00;22:00;11:00;22:00;12:00;22:00"


def read_with(rows):
    api = ServerApi.__new__(ServerApi)
    api._make_request = MagicMock(return_value={"data": [{"configLocation": "test_casu_lokace", "toggleRows": rows}]})
    return api.get_locations()[0]["test_casu_lokace"]


def parse_input(cells):
    processor = LocationTimesProcessor(MagicMock(), url="https://x.example.com", login="login", password="pw",
                                       lang=MagicMock())
    return processor._parse_times(cells, 1)


class LocationDayOrderTest(unittest.TestCase):
    def test_the_days_start_with_sunday_like_the_server_and_the_web_ui(self):
        self.assertEqual(WEEK_DAYS, ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"])

    def test_reading_the_server_schedule_gives_what_the_web_ui_shows(self):
        self.assertEqual(read_with(UI_ROWS), UI_TIMES)

    def test_writing_produces_the_schedule_the_web_ui_shows(self):
        self.assertEqual(ServerApi._create_toggle_rows(UI_TIMES), UI_ROWS)

    def test_pasting_the_exported_row_gives_the_times_the_web_ui_shows(self):
        cells = EXPORTED_ROW.split(";")[1:]

        self.assertEqual(parse_input(cells), UI_TIMES)

    def test_every_day_is_written_to_its_own_day_not_to_a_neighbour(self):
        for index, day in enumerate(WEEK_DAYS):
            times = {name: {"on": "", "off": ""} for name in WEEK_DAYS}
            times[day] = {"on": "08:00", "off": "18:00"}
            with self.subTest(day=day):
                rows = ServerApi._create_toggle_rows(times)

                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["weekDays"], [i == index for i in range(7)])
                self.assertEqual(read_with(rows)[day], {"on": "08:00", "off": "18:00"})

    def test_days_with_the_same_times_share_one_row_like_in_the_web_ui(self):
        times = {day: {"on": "", "off": ""} for day in WEEK_DAYS}
        for day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday"):
            times[day] = {"on": "06:00", "off": "22:00"}
        for day in ("Sunday", "Saturday"):
            times[day] = {"on": "08:00", "off": "22:00"}

        rows = ServerApi._create_toggle_rows(times)

        self.assertEqual(rows, [
            {"turnOn": "08:00", "turnOff": "22:00", "weekDays": [True, False, False, False, False, False, True]},
            {"turnOn": "06:00", "turnOff": "22:00", "weekDays": [False, True, True, True, True, True, False]},
        ])
        self.assertEqual(read_with(rows), times)

    def test_the_same_on_time_with_a_different_off_time_stays_in_separate_rows(self):
        times = {day: {"on": "", "off": ""} for day in WEEK_DAYS}
        times["Monday"] = {"on": "08:00", "off": "18:00"}
        times["Tuesday"] = {"on": "08:00", "off": "20:00"}

        self.assertEqual(len(ServerApi._create_toggle_rows(times)), 2)

    def test_days_without_times_get_no_row(self):
        self.assertEqual(ServerApi._create_toggle_rows({day: {"on": "", "off": ""} for day in WEEK_DAYS}), [])

    def test_a_single_column_pair_lands_on_the_matching_day_of_the_input(self):
        for index, day in enumerate(WEEK_DAYS):
            cells = [""] * 14
            cells[index * 2], cells[index * 2 + 1] = "08:00", "18:00"
            with self.subTest(day=day):
                parsed = parse_input(cells)

                self.assertEqual({name for name, value in parsed.items() if value["on"]}, {day})

    def test_export_then_paste_then_write_keeps_the_schedule_unchanged(self):
        server = MagicMock()
        server.get_locations.return_value = [{"test_casu_lokace": read_with(UI_ROWS)}]
        with patch("processor.csv_generator.ServerApi") as api, tempfile.TemporaryDirectory() as directory:
            api.return_value.__enter__.return_value = server
            path = os.path.join(directory, "plan.csv")
            CSVTaskFactory.create_task("locations_plan", None, url="https://x.example.com", login="login",
                                       password="pw").generate_csv(path)
            with open(path, encoding="utf-8", newline="") as file:
                rows = list(csv.reader(file, delimiter=";"))

        header, exported = rows[0], rows[1]
        self.assertEqual(header[1:3], ["Sunday ON", "Sunday OFF"])
        self.assertEqual(ServerApi._create_toggle_rows(parse_input(exported[1:])), UI_ROWS)

    def test_the_input_template_lists_the_days_in_the_same_order(self):
        for language, days in (("cz", ["neděle", "pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota"]),
                               ("en", WEEK_DAYS)):
            lines = template_lines("set_location_plan", language)
            columns = [line for line in lines if " - " in line and line.startswith("# ") and line[2].isdigit()]
            with self.subTest(language=language):
                self.assertEqual(len(columns), 14)  # the location name has no " - "
                for index, day in enumerate(days):
                    self.assertIn(day, columns[index * 2])
                    self.assertIn(day, columns[index * 2 + 1])

    def test_the_template_example_has_15_cells_with_a_working_week(self):
        example = template_lines("set_location_plan", "cz")[-1].split("\t")

        self.assertEqual(len(example), 15)
        self.assertEqual(example[1:3], ["", ""])  # Sunday
        self.assertEqual(example[3:13], ["08:00", "18:00"] * 5)  # Monday to Friday
        self.assertEqual(example[13:], ["", ""])  # Saturday


if __name__ == "__main__":
    unittest.main()
