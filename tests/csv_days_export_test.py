import csv
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from processor.csv_generator import CSVTaskFactory
from processor.input_processing import convert_days_of_week_to_int, split_list


def playlist(name, days):
    return {"playlist_name": name, "start_date": "2026-01-01T00:00:00Z", "end_date": "2026-12-31T00:00:00Z",
            "days_of_week": days, "start_time": "08:00", "end_time": "18:00"}


class DetailedPlaylistsExportTest(unittest.TestCase):
    """Runs the real export with a stand-in server, so the day names written to the file are what is tested."""

    def export(self, days_per_playlist):
        playlists = [playlist("Default", None)] + [playlist(f"P{i}", days) for i, days in enumerate(days_per_playlist)]
        server = MagicMock()
        server.get_groups_playlists_details.return_value = {"Group 1": playlists}
        with patch("processor.csv_generator.ServerApi") as api, tempfile.TemporaryDirectory() as directory:
            api.return_value.__enter__.return_value = server
            path = os.path.join(directory, "export.csv")
            CSVTaskFactory.create_task("detailed_groups_with_playlists", None, url="https://x.example.com",
                                       login="login", password="pw").generate_csv(path)
            with open(path, encoding="utf-8", newline="") as file:
                return list(csv.reader(file, delimiter=";"))

    def test_all_seven_days_are_written_with_their_api_codes(self):
        rows = self.export([[1, 2, 3, 4, 5, 6, 7]])

        header, row = rows[0], rows[1]
        days = row[header.index("Playlist 1 Days of Week")]
        self.assertEqual(days, "Su, Mo, Tu, We, Th, Fr, Sa")

    def test_saturday_is_sa_not_st(self):
        rows = self.export([[7]])

        self.assertEqual(rows[1][rows[0].index("Playlist 1 Days of Week")], "Sa")

    def test_the_exported_days_paste_back_as_the_same_api_days(self):
        rows = self.export([[2, 4, 6], [1, 7]])
        header, row = rows[0], rows[1]

        for column, expected in (("Playlist 1 Days of Week", [2, 4, 6]), ("Playlist 2 Days of Week", [1, 7])):
            with self.subTest(column=column):
                exported = row[header.index(column)]
                self.assertEqual(convert_days_of_week_to_int(split_list(exported)), expected)


if __name__ == "__main__":
    unittest.main()
