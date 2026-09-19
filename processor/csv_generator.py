from abc import ABC, abstractmethod
from typing import List, Optional, Set
from api_testing.request_calls import ServerApi
import csv
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
import re


@dataclass
class DateFormatError(Exception):
    """Time from server wasn't in expected format"""
    date: str


def iso_to_legible(iso_str):
    """
    Converts an ISO 8601 date string to a legible format without seconds.
    """
    if iso_str == "None" or iso_str is None or iso_str == '':
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        legible_time = dt.strftime("%d.%m.%Y")
        if legible_time:
            return legible_time
    except ValueError:
        raise DateFormatError(iso_str)


def convert_days_of_week_to_str(days_numerical: List[int]) -> Optional[List[str]]:
    if days_numerical is None:
        return None
    convertor = {
        1: "su",
        2: "mo",
        3: "tu",
        4: "we",
        5: "th",
        6: "fr",
        7: "st"
    }
    return [convertor[day] for day in days_numerical]


class CSVTaskFactory:
    @staticmethod
    def create_task(task_type: str, log_handler, *, url: str, login: str, password: str) -> "CSVTask":
        class_map = {
            "groups_with_playlists": GroupWithPlaylistsCSVTask,
            "players_with_groups": PlayersWithGroupsCSVTask,
            "playlist_details": PlaylistsWithAssetsCSVTask,
            "detailed_groups_with_playlists": DetailedGroupsPlaylistsCSVTask,
            "player_locations": PlayerLocationsCSVTask,
            "player_notes": PlayerNotesCSVTask,
            "locations_plan": LocationsPlanCSVTask,
            "player_details": PlayerDetailsCSVTask,
            "player_categories": PlayerLabelsCSVTask,
            "group_settings": GroupSettingsCSVTask,
            "playlist_settings": PlaylistSettingsCSVTask,
            "player_versions": PlayerVersionsCSVTask,
            "group_unused": GroupUnusedCSVTask,
            "playlist_unused": PlaylistUnusedCSVTask,
            "asset_unused": AssetUnusedCSVTask,
            "category_unused": LabelUnusedCSVTask,
            "location_unused": LocationUnusedCSVTask,
            "label_unused": LabelUnusedCSVTask,
            "asset_details": AssetDetailsCSVTask,
            "player_overview": PlayerOverviewCSVTask,
            "asset_validity": AssetsValidityCSVTask,
            "identical_groups": GroupsWithIdenticalPlaylistsCSVTask,
            "additional_playlists": PlayerAdditionalPlaylistsCSVTask
        }
        task_class = class_map.get(task_type)
        if not task_class:
            raise ValueError(f"Unknown task type: {task_type}")
        return task_class(log_handler, url=url, login=login, password=password)


class CSVTask(ABC):
    def __init__(self, log_handler, *, url: str, login: str, password: str):
        self.logger = log_handler
        self._login_info = {
            "login": login,
            "password": password,
            "url": url + "/api"
        }

    @abstractmethod
    def generate_csv(self, output_file: str) -> None:
        pass

    @abstractmethod
    def get_headers(self, data: list) -> [str]:
        pass

    @staticmethod
    def _write_to_csv(output_file: str, data: list, headers: [str]) -> None:
        with open(output_file, "w", newline='', encoding='utf-8') as file:
            csvwriter = csv.writer(file, delimiter=';')
            if headers:
                csvwriter.writerow(headers)
            csvwriter.writerows(data)

    @staticmethod
    def _generate_headers(data: list) -> [str]:
        max_length = max(len(row) for row in data)
        headers = [f"Column {i+1}" for i in range(max_length)]
        return headers


class GroupWithPlaylistsCSVTask(CSVTask):
    def generate_csv(self, output_file: str) -> None:
        csv_lines = []
        with ServerApi(**self._login_info) as server:
            response = server.get_groups_playlists()
            for group in response.keys():
                playlist_data = self._normalize_playlists(response[group])
                csv_lines.append([group] + playlist_data)
        headers = self.get_headers(csv_lines)
        self._write_to_csv(output_file, csv_lines, headers)

    @staticmethod
    def _normalize_playlists(playlists: [(str, str, str, str, str)]) -> [str]:
        normalized = []
        try:
            normalized = [playlists[0][0]]
        except IndexError:
            pass
        for playlist in playlists[1:]:
            normalized.append(playlist[0])
            normalized.append(iso_to_legible(playlist[1]) if playlist[1] else playlist[1])
            normalized.append(iso_to_legible(playlist[2]) if playlist[2] else playlist[2])
            normalized.append(playlist[3])
            normalized.append(playlist[4])
        return normalized

    def get_headers(self, data: list) -> [str]:
        headers = ["Group", "Default Playlist"]
        max_length = max(len(row) for row in data)
        headers.extend([f"Playlist {i//5 + 1} {field}"
                        for i, field in enumerate(
                        ["Name", "Start Date", "End Date", "Start Time", "End Time"] * ((max_length - 1) // 5)
                        )])
        return headers


class PlayersWithGroupsCSVTask(CSVTask):
    def generate_csv(self, output_file: str) -> None:
        csv_lines = []
        with ServerApi(**self._login_info) as server:
            response = server.get_players_groups()
            for player, group in response:
                csv_lines.append([player, group])
        headers = self.get_headers(csv_lines)
        self._write_to_csv(output_file, csv_lines, headers)

    def get_headers(self, data: list) -> [str]:
        return ["Player", "Group"]


class PlaylistsWithAssetsCSVTask(CSVTask):
    def generate_csv(self, output_file: str) -> None:
        csv_lines = []
        with ServerApi(**self._login_info) as server:
            playlists = server.get_all_playlists_details()
            for playlist in playlists:
                playlist_name, assets = playlist
                # asset_details = self._normalize_assets(assets)
                csv_lines.append([playlist_name] + assets)
        headers = self.get_headers(csv_lines)
        self._write_to_csv(output_file, csv_lines, headers)

    @staticmethod
    def _normalize_assets(assets_raw: [(str, int)]) -> [str]:
        normalized = []
        for asset in assets_raw:
            normalized.append(asset[0])
            normalized.append(asset[1])
        return normalized

    def get_headers(self, data: list) -> [str]:
        headers = ["Playlist"]
        max_assets = max((len(row) - 1) for row in data)
        for i in range(max_assets):
            headers.append(f"Asset {i+1} Name")
        return headers


class DetailedGroupsPlaylistsCSVTask(CSVTask):
    def generate_csv(self, output_file: str) -> None:
        csv_lines = []
        with ServerApi(**self._login_info) as server:
            groups_playlists = server.get_groups_playlists_details()
            for group, playlists in groups_playlists.items():
                # Invariant: One playlist is always assigned in dtb, with TV_OFF
                group_playlist = []
                try:
                    group_playlist = [playlists[0]["playlist_name"]]
                except IndexError:
                    pass
                for playlist in playlists[1:]:
                    playlist_name = playlist["playlist_name"]
                    start_date = iso_to_legible(playlist["start_date"])
                    end_date = iso_to_legible(playlist["end_date"])
                    days_of_week = convert_days_of_week_to_str(playlist["days_of_week"])
                    if days_of_week is not None:
                        days_of_week = list(map(lambda x: x.capitalize(),
                                                days_of_week))
                        days_of_week = ', '.join(days_of_week)
                    start_time = playlist["start_time"]
                    end_time = playlist["end_time"]
                    if days_of_week == "on":
                        days_of_week = ""
                    group_playlist += [playlist_name, start_date, end_date, days_of_week, start_time, end_time]
                csv_lines.append([group] + group_playlist)
        headers = self.get_headers(csv_lines)
        self._write_to_csv(output_file, csv_lines, headers)

    def get_headers(self, data: list) -> [str]:
        headers = ["Group", "Default Playlist"]
        max_length = max(len(row) for row in data)
        headers.extend([
            f"Playlist {i//6 + 1} {field}"
            for i, field in enumerate(
                ["Name", "Start Date", "End Date", "Days of Week", "Start Time", "End Time"] * ((max_length - 1) // 6)
            )])
        return headers


class PlayerLocationsCSVTask(CSVTask):
    def generate_csv(self, output_file: str) -> None:
        csv_lines = []
        with ServerApi(**self._login_info) as server:
            response = server.get_player_locations()
            for player, location in response:
                csv_lines.append([player, location])
        headers = self.get_headers(csv_lines)
        self._write_to_csv(output_file, csv_lines, headers)

    def get_headers(self, data: list) -> [str]:
        return ["Player", "Location"]


class PlayerNotesCSVTask(CSVTask):
    def generate_csv(self, output_file: str) -> None:
        csv_lines = []
        with ServerApi(**self._login_info) as server:
            response = server.get_player_notes()
            for player, notes in response:
                csv_lines.append([player, notes])
        headers = self.get_headers(csv_lines)
        self._write_to_csv(output_file, csv_lines, headers)

    def get_headers(self, data: list) -> [str]:
        return ["Player", "Notes"]


class LocationsPlanCSVTask(CSVTask):
    def generate_csv(self, output_file: str) -> None:
        csv_lines = []
        with ServerApi(**self._login_info) as server:
            locations_data = server.get_locations()
            for location in locations_data:
                for location_name, times in location.items():
                    row = [location_name]
                    for day in ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]:
                        row.append(times[day]["on"])
                        row.append(times[day]["off"])
                    csv_lines.append(row)
        headers = self.get_headers(csv_lines)
        self._write_to_csv(output_file, csv_lines, headers)

    def get_headers(self, data: list) -> [str]:
        headers = ["Location"]
        for day in ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]:
            headers.append(f"{day} ON")
            headers.append(f"{day} OFF")
        return headers


class PlayerDetailsCSVTask(CSVTask):
    def generate_csv(self, output_file: str) -> None:
        csv_lines = []
        with ServerApi(**self._login_info) as server:
            players = server.get_players_details()
            for player in players:
                name, status, last_connect, sync, version, ip, uptime, temp = player
                csv_lines.append([name,
                                  status,
                                  iso_to_legible(last_connect),
                                  sync,
                                  version,
                                  ip,
                                  uptime,
                                  temp
                                  ])
        headers = self.get_headers(csv_lines)
        self._write_to_csv(output_file, csv_lines, headers)

    def get_headers(self, data: list) -> [str]:
        return ["Player",
                "Online Status",
                "Last Connection",
                "Last Sync",
                "SW Version",
                "IP Address",
                "Uptime",
                "Last Temperature"]


class PlayerLabelsCSVTask(CSVTask):
    def generate_csv(self, output_file: str) -> None:
        csv_lines = []
        with ServerApi(**self._login_info) as server:
            response = server.get_player_labels()
            for player, labels in response:
                csv_lines.append([player] + labels)
        headers = self.get_headers(csv_lines)
        self._write_to_csv(output_file, csv_lines, headers)

    def get_headers(self, data: list) -> [str]:
        max_labels = max(len(row) - 1 for row in data)
        headers = ["Player"]
        headers.extend([f"Category {i+1}" for i in range(max_labels)])
        return headers


class PlayerAdditionalPlaylistsCSVTask(CSVTask):
    def generate_csv(self, output_file: str) -> None:
        csv_lines = []
        with ServerApi(**self._login_info) as server:
            response = server.get_additional_playlists()
            for player, labels in response:
                csv_lines.append([player] + labels)
        headers = self.get_headers(csv_lines)
        self._write_to_csv(output_file, csv_lines, headers)

    def get_headers(self, data: list) -> [str]:
        max_labels = max(len(row) - 1 for row in data)
        headers = ["Player"]
        headers.extend([f"Playlist {i+1}" for i in range(max_labels)])
        return headers

class GroupSettingsCSVTask(CSVTask):
    def generate_csv(self, output_file: str) -> None:
        csv_lines = []
        with (ServerApi(**self._login_info) as server):
            response = server.get_group_settings()
            for group, resolution, orientation, auto_restart, auto_deploy, \
                    combine, eligible_playlists, on_time, off_time, video_player in response:
                auto_restart_time = self.format_time(auto_restart) if auto_restart else None
                auto_deploy_time = self.format_time(auto_deploy) if auto_deploy else None

                csv_lines.append([group,
                                  resolution,
                                  orientation,
                                  auto_restart_time,
                                  auto_deploy_time,
                                  combine,
                                  eligible_playlists,
                                  on_time,
                                  off_time,
                                  video_player
                                  ])
        headers = self.get_headers(csv_lines)
        self._write_to_csv(output_file, csv_lines, headers)

    @staticmethod
    def format_time(time_str: str) -> Optional[str]:
        if time_str:
            try:
                dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                desired_timezone = timezone(timedelta(hours=1))
                local_dt = dt.astimezone(desired_timezone)
                return local_dt.strftime("%H:%M")
            except ValueError:
                return time_str
        return None

    def get_headers(self, data: list) -> [str]:
        return ["Group",
                "Resolution",
                "Orientation",
                "Auto Restart",
                "Auto Deploy",
                "Combine Default Playlist",
                "Play All Eligible Playlists",
                "LCD On", "LCD, Off", "default/mpv/cvlc"]


class PlaylistSettingsCSVTask(CSVTask):
    def generate_csv(self, output_file: str) -> None:
        csv_lines = []
        with ServerApi(**self._login_info) as server:
            response = server.get_playlists_settings()
            for name, domination_time in response:
                csv_lines.append([name, domination_time])
        headers = self.get_headers(csv_lines)
        self._write_to_csv(output_file, csv_lines, headers)

    def get_headers(self, data: list) -> [str]:
        return ["Playlist", "Domination Interval"]


class PlayerVersionsCSVTask(CSVTask):
    def generate_csv(self, output_file: str) -> None:
        csv_lines = []
        with ServerApi(**self._login_info) as server:
            player_versions = server.get_versions()
            for name, version in player_versions:
                csv_lines.append([name, "\"" + version + "\""])
        headers = self.get_headers(csv_lines)
        self._write_to_csv(output_file, csv_lines, headers)

    def get_headers(self, data: list) -> [str]:
        return ["Player", "Version"]


class UnusedCSVTask(CSVTask):
    skip_names: Set[str]

    @abstractmethod
    def generate_csv(self, output_file: str) -> None:
        pass

    def skip_check(self, entity: str) -> bool:
        return entity in self.skip_names

    def generate_csv_by_method(self, output_file: str, server_method) -> None:
        csv_lines = []
        for entity in server_method():
            if self.skip_check(entity):
                continue
            csv_lines.append([entity])
        headers = self.get_headers(csv_lines)
        self._write_to_csv(output_file, csv_lines, headers)

    @abstractmethod
    def get_headers(self, data: list) -> [str]:
        pass

    @staticmethod
    def get_labeled_test(server_method):
        labels = ["test", "Test", "TEst", "TESt", "TEST", "tEST", "teST", "tesT", "tESt", "teSt", "tEst"]
        labeled_entities = []
        for label in labels:
            labeled_entities += server_method(label)
        return set(labeled_entities)


class GroupUnusedCSVTask(UnusedCSVTask):

    def generate_csv(self, output_file: str) -> None:
        with ServerApi(**self._login_info) as server:
            self.skip_names = self.get_labeled_test(server.get_groups_by_label)
            self.generate_csv_by_method(output_file, server.get_unused_groups)

    def get_headers(self, data: list) -> [str]:
        return ["Group"]

    def skip_check(self, entity: str) -> bool:
        return entity in self.skip_names


class LabelUnusedCSVTask(UnusedCSVTask):
    test_pattern = re.compile(r"[tT][eE][sS][tT]")

    def generate_csv(self, output_file: str) -> None:
        with ServerApi(**self._login_info) as server:
            self.generate_csv_by_method(output_file, server.get_unused_labels)

    def skip_check(self, entity: str) -> bool:
        return bool(re.match(self.test_pattern, entity))

    def get_headers(self, data: list) -> [str]:
        return ["Category"]


class PlaylistUnusedCSVTask(UnusedCSVTask):
    def generate_csv(self, output_file: str) -> None:
        with ServerApi(**self._login_info) as server:
            self.skip_names = self.get_labeled_test(server.get_playlists_by_label)
            self.generate_csv_by_method(output_file, server.get_unused_playlists)

    def get_headers(self, data: list) -> [str]:
        return ["Playlist"]


class AssetUnusedCSVTask(UnusedCSVTask):
    def generate_csv(self, output_file: str) -> None:
        with ServerApi(**self._login_info) as server:
            self.skip_names = self.get_labeled_test(server.get_assets_by_label)
            self.generate_csv_by_method(output_file, server.get_unused_assets)

    def get_headers(self, data: list) -> [str]:
        return ["Asset"]


class LocationUnusedCSVTask(UnusedCSVTask):
    def generate_csv(self, output_file: str) -> None:
        with ServerApi(**self._login_info) as server:
            self.skip_names = self.get_labeled_test(server.get_locations_by_label)
            self.generate_csv_by_method(output_file, server.get_unused_locations)

    def get_headers(self, data: list) -> [str]:
        return ["Location"]


class AssetDetailsCSVTask(CSVTask):
    def generate_csv(self, output_file: str) -> None:
        csv_lines = []
        with ServerApi(**self._login_info) as server:
            assets_details = server.get_assets_details()
            for asset in assets_details:
                asset_name = asset["name"]
                asset_type = asset["type"]
                asset_duration = asset["duration"]
                asset_size = asset["size"]
                asset_resolution = f'{asset["resolution"]["width"]}x{asset["resolution"]["height"]}'
                asset_validity = (
                    f'{iso_to_legible(asset["validity"]["startdate"])} - '
                    f'{iso_to_legible(asset["validity"]["enddate"])}'
                )
                asset_playlists = ", ".join([i for i in asset.get("playlists", []) if i])
                asset_labels = ", ".join([i for i in asset.get("labels", []) if i])
                csv_lines.append([
                    asset_name, asset_type, asset_duration, asset_size,
                    asset_resolution, asset_validity, asset_playlists, asset_labels
                ])
        headers = self.get_headers(csv_lines)
        self._write_to_csv(output_file, csv_lines, headers)

    def get_headers(self, data: list) -> [str]:
        return [
            "Name", "Type", "Duration", "Size", "Resolution",
            "Validity Period", "Playlists", "Categories"
        ]


class PlayerOverviewCSVTask(CSVTask):
    def generate_csv(self, output_file: str) -> None:
        csv_lines = []
        with ServerApi(**self._login_info) as server:
            player_details = server.get_player_details_overview()
            for player in player_details:
                player_name = player.get("name", "")
                group = player.get("group", "")
                version = f"v: {player.get('version', 'unknown')}"
                ip_address = player.get("ip", "")
                last_report = iso_to_legible(player["last_report"]) if player.get("last_report") else "N/A"
                location = player.get("location", "")
                temperature = player.get("temperature", "")
                labels = ", ".join([str(i) for i in player.get("labels", []) if i])
                note = player.get("notes", "")
                current_playlist = player.get("current_playlist", "")
                csv_lines.append([
                    player_name, group, version, ip_address,
                    last_report, location, temperature, labels,
                    note, current_playlist
                ])
        headers = self.get_headers(csv_lines)
        self._write_to_csv(output_file, csv_lines, headers)

    def get_headers(self, data: list) -> [str]:
        return [
            "Player Name", "Group", "Version", "IP Address",
            "Last Report", "Location", "Temperature", "Categories", "Note",
            "Current Playlist"
        ]


class AssetsValidityCSVTask(CSVTask):
    def generate_csv(self, output_file: str) -> None:
        csv_lines = []
        with ServerApi(**self._login_info) as server:
            assets_validity = server.get_assets_validity()
            for asset_name, start_date, end_date, start_hour, end_hour in assets_validity:
                csv_lines.append([
                    asset_name, iso_to_legible(start_date), iso_to_legible(end_date), start_hour,  end_hour
                ])
        headers = self.get_headers(csv_lines)
        self._write_to_csv(output_file, csv_lines, headers)

    def get_headers(self, data: list) -> [str]:
        return ["Asset Name", "Validity Start Date", "Validity End Date", "Start Hour", "End Hour"]


class GroupsWithIdenticalPlaylistsCSVTask(CSVTask):
    def generate_csv(self, output_file: str) -> None:
        with ServerApi(**self._login_info) as server:
            groups_playlists = server.get_groups_playlists_details()
            group_settings = server.get_group_settings()

            playlist_groups_map = {}
            for group, playlists in groups_playlists.items():
                orientation = next(
                    (setting[2] for setting in group_settings if setting[0] == group), None)

                normalized_playlists = tuple(sorted([
                    (playlist["playlist_name"], iso_to_legible(playlist["start_date"]),
                     iso_to_legible(playlist["end_date"]))
                    for playlist in playlists
                ]))

                key = (normalized_playlists, orientation)

                if key not in playlist_groups_map:
                    playlist_groups_map[key] = []
                playlist_groups_map[key].append(group)

            identical_groups = [groups for groups in playlist_groups_map.values() if len(groups) > 1]

            csv_lines = []
            for groups in identical_groups:
                csv_lines.append(groups)

        headers = self.get_headers(csv_lines)
        self._write_to_csv(output_file, csv_lines, headers)

    def get_headers(self, data: list) -> [str]:
        if not data:
            return []
        max_length = max(len(row) for row in data)
        headers = [f"Group {i + 1}" for i in range(max_length)]
        return headers
