import unittest
from unittest.mock import patch, MagicMock
import tempfile
import os
import csv
from processor.csv_generator import (
    DateFormatError,
    iso_to_legible,
    convert_days_of_week_to_str,
    GroupWithPlaylistsCSVTask,
    PlayersWithGroupsCSVTask,
    PlaylistsWithAssetsCSVTask,
    DetailedGroupsPlaylistsCSVTask,
    PlayerLocationsCSVTask,
    PlayerNotesCSVTask,
    LocationsPlanCSVTask,
    PlayerDetailsCSVTask,
    PlayerLabelsCSVTask,
    GroupSettingsCSVTask,
    PlayerVersionsCSVTask,
    GroupUnusedCSVTask,
    PlaylistUnusedCSVTask,
    AssetUnusedCSVTask,
    AssetDetailsCSVTask,
    PlayerOverviewCSVTask,
)

class CSVTaskTestCase(unittest.TestCase):
    def setUp(self):
        self.log_handler = MagicMock()
        self.url = "http://testserver"
        self.login = "testuser"
        self.password = "testpassword"

        self.mock_post = patch('requests.post').start()
        self.mock_request = patch('requests.request').start()

        self.mock_post.return_value.json.return_value = {"token": "testtoken"}
        self.mock_request.return_value.json.return_value = {"success": True, "data": {"objects": []}}
        self.mock_request.return_value.ok = True

    def tearDown(self):
        patch.stopall()

    def _read_csv_file(self, file_path):
        with open(file_path, 'r', newline='', encoding='utf-8-sig') as f:
            reader = csv.reader(f, delimiter=';')
            return list(reader)

    @staticmethod
    def _responses_by_endpoint(mapping):
        """
        A `requests.request` side effect for tasks that hit several different endpoints (some of them
        repeatedly, e.g. the "skip test-labeled entities" lookup calls /groups or /files once per label
        casing). Matches by the URL's suffix; a call to an endpoint not in `mapping` (namely the final
        DELETE /session) gets a bare success response.
        """
        def side_effect(method, url, **kwargs):
            for suffix, payload in mapping.items():
                if url.endswith(suffix):
                    response = MagicMock()
                    response.ok = True
                    response.json.return_value = payload
                    return response
            response = MagicMock()
            response.ok = True
            response.json.return_value = {"success": True}
            return response
        return side_effect

    def test_group_with_playlists_csv_task(self):
        self.mock_request.return_value.json.return_value = {"success": True, "data": [{"name": "Group 1", "playlists": [
            {"name": "Playlist 1",
             "settings": {"startdate": "2023-07-15T12:00:00Z", "enddate": "2023-07-20T12:00:00Z", "starttime": "08:00",
                          "endtime": "20:00"}},
            {"name": "Playlist 2",
             "settings": {"startdate": "2023-07-15T12:00:00Z", "enddate": "2023-07-20T12:00:00Z", "starttime": "08:00",
                          "endtime": "20:00"}}
        ]}]}
        task = GroupWithPlaylistsCSVTask(self.log_handler, url=self.url, login=self.login, password=self.password)

        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            task.generate_csv(tmp_file.name)
            tmp_file_path = tmp_file.name

        content = self._read_csv_file(tmp_file_path)
        os.remove(tmp_file_path)
        expected_content = [
            ["Group", "Default Playlist", "Playlist 1 Name", "Playlist 1 Start Date", "Playlist 1 End Date",
             "Playlist 1 Start Time", "Playlist 1 End Time"],
            ["Group 1", "Playlist 1", "Playlist 2", "15.07.2023", "20.07.2023", "08:00", "20:00"]
        ]

        self.assertEqual(content, expected_content)

    def test_players_with_groups_csv_task(self):
        self.mock_request.return_value.json.return_value = {"success": True, 
            "data": {"objects": [{"name": "Player 1", "group": {"name": "Group 1"}}]}}
        task = PlayersWithGroupsCSVTask(self.log_handler, url=self.url, login=self.login, password=self.password)

        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            task.generate_csv(tmp_file.name)
            tmp_file_path = tmp_file.name

        content = self._read_csv_file(tmp_file_path)
        os.remove(tmp_file_path)
        expected_content = [
            ["Player", "Group"],
            ["Player 1", "Group 1"]
        ]

        self.assertEqual(content, expected_content)

    def test_playlists_with_assets_csv_task(self):
        self.mock_request.return_value.json.return_value = {"success": True, "data": [{"name": "Playlist 1", "assets": [{"filename": "Asset 1"}]}]}
        task = PlaylistsWithAssetsCSVTask(self.log_handler, url=self.url, login=self.login, password=self.password)

        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            task.generate_csv(tmp_file.name)
            tmp_file_path = tmp_file.name

        content = self._read_csv_file(tmp_file_path)
        os.remove(tmp_file_path)
        expected_content = [
            ["Playlist", "Asset 1 Name"],
            ["Playlist 1", "Asset 1"]
        ]

        self.assertEqual(content, expected_content)

    def test_detailed_groups_playlists_csv_task(self):
        self.mock_request.return_value.json.return_value = {"success": True, "data": [{"name": "Group 1", "playlists": [
            {"name": "Playlist 1",
             "settings": {"startdate": "2023-07-15T12:00:00Z", "enddate": "2023-07-20T12:00:00Z", "weekdays": [1, 2, 3],
                          "starttime": "08:00", "endtime": "20:00"}},
            {"name": "Playlist 2",
             "settings": {"startdate": "2023-07-15T12:00:00Z", "enddate": "2023-07-20T12:00:00Z", "weekdays": [1, 2, 3],
                          "starttime": "08:00", "endtime": "20:00"}}
        ]}]}
        task = DetailedGroupsPlaylistsCSVTask(self.log_handler, url=self.url, login=self.login, password=self.password)

        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            task.generate_csv(tmp_file.name)
            tmp_file_path = tmp_file.name

        content = self._read_csv_file(tmp_file_path)
        os.remove(tmp_file_path)
        expected_content = [
            ["Group", "Default Playlist", "Playlist 1 Name", "Playlist 1 Start Date", "Playlist 1 End Date",
             "Playlist 1 Days of Week", "Playlist 1 Start Time", "Playlist 1 End Time"],
            ["Group 1", "Playlist 1", "Playlist 2", "15.07.2023", "20.07.2023", "Su, Mo, Tu", "08:00", "20:00"]
        ]

        self.assertEqual(content, expected_content)

    def test_player_locations_csv_task(self):
        self.mock_request.return_value.json.return_value = {"success": True, 
            "data": {"objects": [{"name": "Player 1", "configLocation": "Location 1"}]}}
        task = PlayerLocationsCSVTask(self.log_handler, url=self.url, login=self.login, password=self.password)

        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            task.generate_csv(tmp_file.name)
            tmp_file_path = tmp_file.name

        content = self._read_csv_file(tmp_file_path)
        os.remove(tmp_file_path)
        expected_content = [
            ["Player", "Location"],
            ["Player 1", "Location 1"]
        ]

        self.assertEqual(content, expected_content)

    def test_player_notes_csv_task(self):
        self.mock_request.return_value.json.return_value = {"success": True, 
            "data": {"objects": [{"name": "Player 1", "notes": "Note 1"}]}}
        task = PlayerNotesCSVTask(self.log_handler, url=self.url, login=self.login, password=self.password)

        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            task.generate_csv(tmp_file.name)
            tmp_file_path = tmp_file.name

        content = self._read_csv_file(tmp_file_path)
        os.remove(tmp_file_path)
        expected_content = [
            ["Player", "Notes"],
            ["Player 1", "Note 1"]
        ]

        self.assertEqual(content, expected_content)

    def test_locations_plan_csv_task(self):
        self.mock_request.return_value.json.return_value = {"success": True, 
            "data": [
                {
                    "configLocation": "Location 1",
                    "toggleRows": [
                        {"turnOn": "08:02", "turnOff": "18:30",
                         "weekDays": [False, True, False, False, False, False, False]},
                        {"turnOn": "09:02", "turnOff": "18:30",
                         "weekDays": [False, False, True, False, False, False, False]},
                        {"turnOn": "10:02", "turnOff": "18:30",
                         "weekDays": [False, False, False, True, False, False, False]},
                        {"turnOn": "11:02", "turnOff": "18:30",
                         "weekDays": [False, False, False, False, True, False, False]},
                        {"turnOn": "12:02", "turnOff": "18:30",
                         "weekDays": [False, False, False, False, False, True, False]}
                    ]
                }
            ]
        }
        task = LocationsPlanCSVTask(self.log_handler, url=self.url, login=self.login, password=self.password)

        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            task.generate_csv(tmp_file.name)
            tmp_file_path = tmp_file.name

        content = self._read_csv_file(tmp_file_path)
        os.remove(tmp_file_path)
        expected_content = [
            ["Location", "Sunday ON", "Sunday OFF", "Monday ON", "Monday OFF", "Tuesday ON", "Tuesday OFF",
             "Wednesday ON", "Wednesday OFF", "Thursday ON", "Thursday OFF", "Friday ON", "Friday OFF", "Saturday ON",
             "Saturday OFF"],
            ["Location 1", "", "", "08:02", "18:30", "09:02", "18:30", "10:02", "18:30", "11:02", "18:30", "12:02",
             "18:30", "", ""]
        ]

        self.assertEqual(content, expected_content)

    def test_player_details_csv_task(self):
        self.mock_request.return_value.json.return_value = {"success": True, "data": {"objects": [{
            "name": "Player 1", "tvStatus": "Online", "lastReported": "2023-07-15T12:00:00Z",
            "lastUpload": "44", "version": "v1.0", "ip": "192.168.0.1", "uptime": "24h",
            "piTemperature": "75C"}]}}

        task = PlayerDetailsCSVTask(self.log_handler, url=self.url, login=self.login, password=self.password)

        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            task.generate_csv(tmp_file.name)
            tmp_file_path = tmp_file.name

        content = self._read_csv_file(tmp_file_path)
        os.remove(tmp_file_path)
        expected_content = [
            ["Player", "Online Status", "Last Connection", "Last Sync", "SW Version", "IP Address", "Uptime",
             "Last Temperature"],
            ["Player 1", "Online", "15.07.2023", "44", "v1.0", "192.168.0.1", "24h", "75C"]
        ]

        self.assertEqual(content, expected_content)

    def test_player_labels_csv_task(self):
        self.mock_request.return_value.json.return_value = {"success": True, 
            "data": {"objects": [{"name": "Player 1", "labels": ["Label 1"]}]}}
        task = PlayerLabelsCSVTask(self.log_handler, url=self.url, login=self.login, password=self.password)

        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            task.generate_csv(tmp_file.name)
            tmp_file_path = tmp_file.name

        content = self._read_csv_file(tmp_file_path)
        os.remove(tmp_file_path)
        expected_content = [
            ["Player", "Category 1"],
            ["Player 1", "Label 1"]
        ]

        self.assertEqual(content, expected_content)

    def test_group_settings_csv_task(self):
        self.mock_request.return_value.json.return_value = {"success": True, "data": [
            {"name": "Group 1", "resolution": "1920x1080", "orientation": "landscape", "reboot": {
                "time": "08:00", "enable": "true"
            },
             "everydayDeployTime": "20:00", "deployEveryday": "true"}]}
        task = GroupSettingsCSVTask(self.log_handler, url=self.url, login=self.login, password=self.password)

        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            task.generate_csv(tmp_file.name)
            tmp_file_path = tmp_file.name

        content = self._read_csv_file(tmp_file_path)
        os.remove(tmp_file_path)
        expected_content = [
            ["Group", "Resolution", "Orientation", "Auto Restart", "Auto Deploy", "Combine Default Playlist",
             "Play All Eligible Playlists", "LCD On", "LCD, Off", "default/mpv/cvlc"],
            ["Group 1", "1920x1080", "landscape", "08:00", "20:00", "", "", "", "", ""]
        ]

        self.assertEqual(content, expected_content)

    def test_player_versions_csv_task(self):
        self.mock_request.return_value.json.return_value = {"success": True, 
            "data": {"objects": [{"name": "Player 1", "version": "v1.0"}]}}
        task = PlayerVersionsCSVTask(self.log_handler, url=self.url, login=self.login, password=self.password)

        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            task.generate_csv(tmp_file.name)
            tmp_file_path = tmp_file.name

        content = self._read_csv_file(tmp_file_path)
        os.remove(tmp_file_path)
        expected_content = [
            ["Player", "Version"],
            ["Player 1", "\"v1.0\""]
        ]

        self.assertEqual(content, expected_content)

    def test_group_unused_csv_task(self):
        # /groups is hit both by the "skip test-labeled groups" lookup (once per case variant of "test")
        # and by get_group_names(); /players is hit once by get_players_groups().
        self.mock_request.side_effect = self._responses_by_endpoint({
            "/groups": {"success": True, "data": [{"name": "Group 1"}, {"name": "Group 2"}]},
            "/players": {"success": True, "data": {"objects": [{"name": "Player 1", "group": {"name": "Group 1"}}]}},
        })

        task = GroupUnusedCSVTask(self.log_handler, url=self.url, login=self.login, password=self.password)

        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            task.generate_csv(tmp_file.name)
            tmp_file_path = tmp_file.name

        content = self._read_csv_file(tmp_file_path)
        os.remove(tmp_file_path)
        expected_content = [
            ["Group"],
            ["Group 2"]
        ]

        self.assertEqual(content, expected_content)

    def test_playlist_unused_csv_task(self):
        # /playlists is hit both by the "skip test-labeled playlists" lookup and by get_playlist_names();
        # /groups is hit once by get_groups_playlists().
        self.mock_request.side_effect = self._responses_by_endpoint({
            "/playlists": {"success": True, "data": [{"name": "Playlist 1"}, {"name": "Playlist 2"}]},
            "/groups": {"success": True, "data": [{"name": "Group 1", "playlists": [{"name": "Playlist 1"}]}]},
        })

        task = PlaylistUnusedCSVTask(self.log_handler, url=self.url, login=self.login, password=self.password)

        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            task.generate_csv(tmp_file.name)
            tmp_file_path = tmp_file.name

        content = self._read_csv_file(tmp_file_path)
        os.remove(tmp_file_path)
        expected_content = [
            ["Playlist"],
            ["Playlist 2"]
        ]

        self.assertEqual(content, expected_content)

    def test_asset_unused_csv_task(self):
        # /files is hit both by the "skip test-labeled assets" lookup and by get_all_assets();
        # /playlists is hit once by get_used_assets().
        self.mock_request.side_effect = self._responses_by_endpoint({
            "/files": {"success": True, "data": {"dbdata": [{"name": "Asset 1"}, {"name": "Asset 2"}]}},
            "/playlists": {"success": True, "data": [{"assets": [{"filename": "Asset 1"}]}]},
        })

        task = AssetUnusedCSVTask(self.log_handler, url=self.url, login=self.login, password=self.password)

        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            task.generate_csv(tmp_file.name)
            tmp_file_path = tmp_file.name

        content = self._read_csv_file(tmp_file_path)
        os.remove(tmp_file_path)
        expected_content = [
            ["Asset"],
            ["Asset 2"]
        ]

        self.assertEqual(content, expected_content)

    def test_asset_details_csv_task(self):
        self.mock_request.return_value.json.return_value = {"success": True, "data": {"dbdata": [
            {"name": "Asset 1", "type": "video", "duration": '120', "size": '500',
             "resolution": {"width": '1920', "height": '1080'},
             "validity": {"startdate": "2023-07-15T12:00:00Z", "enddate": "2023-07-20T12:00:00Z"},
             "playlists": ["Playlist 1"], "labels": ["Label 1"]}]}}
        task = AssetDetailsCSVTask(self.log_handler, url=self.url, login=self.login, password=self.password)

        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            task.generate_csv(tmp_file.name)
            tmp_file_path = tmp_file.name

        content = self._read_csv_file(tmp_file_path)
        os.remove(tmp_file_path)
        expected_content = [
            ["Name", "Type", "Duration", "Size", "Resolution", "Validity Period", "Playlists", "Categories"],
            ["Asset 1", "video", '120', '500', "1920x1080", "15.07.2023 - 20.07.2023", "Playlist 1", "Label 1"]
        ]

        self.assertEqual(content, expected_content)

    def test_player_overview_csv_task(self):
        self.mock_request.return_value.json.return_value = {"success": True, "data": {"objects": [
            {"name": "Player 1", "group": {"name": "Group 1"}, "version": "v1.0", "ip": "192.168.0.1",
             "lastReported": "2023-07-15T12:00:00Z", "configLocation": "Location 1", "piTemperature": "75C",
             "labels": ["Label 1"], "currentPlaylist": "Playlist 1"}]}}
        task = PlayerOverviewCSVTask(self.log_handler, url=self.url, login=self.login, password=self.password)

        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            task.generate_csv(tmp_file.name)
            tmp_file_path = tmp_file.name

        content = self._read_csv_file(tmp_file_path)
        os.remove(tmp_file_path)
        expected_content = [
            ["Player Name", "Group", "Version", "IP Address", "Last Report", "Location", "Temperature", "Categories",
             "Note", "Current Playlist"],
            ["Player 1", "Group 1", "v: v1.0", "192.168.0.1", "15.07.2023", "Location 1", "75C", "Label 1", "",
             "Playlist 1"]
        ]

        self.assertEqual(content, expected_content)

    def test_iso_to_legible(self):
        legible_time = iso_to_legible("2023-07-15T12:00:00Z")
        self.assertEqual(legible_time, "15.07.2023")
        self.assertRaises(DateFormatError, iso_to_legible, "invalid-date")

    def test_convert_days_of_week_to_str(self):
        self.assertEqual(convert_days_of_week_to_str([1, 2, 3]), ["su", "mo", "tu"])
        self.assertEqual(convert_days_of_week_to_str([4, 5, 6, 7]), ["we", "th", "fr", "sa"])


if __name__ == "__main__":
    unittest.main()
