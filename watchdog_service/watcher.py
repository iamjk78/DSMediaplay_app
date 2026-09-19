import time
import logging
from dataclasses import dataclass
from typing import Set
from api_testing.request_calls import ServerApi
from watchdog_service.config_processor import ConfigManager
from util.internet_com import StatusReporter
from watchdog_service.file_saver import FileSaver


@dataclass
class StatusError(Exception):
    status: str
    players: Set[str]


class PlayerStatusWatcher:
    def __init__(self, cfg_manager: ConfigManager, reporter: StatusReporter):
        self.report = reporter.report
        self.login = cfg_manager.get_login()
        self.interval = cfg_manager.interval
        self.green = cfg_manager.active
        self.cfg_manager = cfg_manager
        self.saver = FileSaver(cfg_manager.admin)
        logging.basicConfig(level=logging.INFO)

    def main_loop(self):
        """Main loop to continuously check player statuses at the defined interval."""
        while True:
            self.check_player_statuses()
            time.sleep(self.interval)

    def check_player_statuses(self):
        """Fetch player statuses and check them against expected values."""
        try:
            with ServerApi(**self.login) as server:
                self.check_and_report_status(server, 'playing', self.green,
                                             server.get_online_players)
        except Exception as e:
            logging.error(f"Error fetching player details: {e}")

    def check_and_report_status(self,
                                server: ServerApi,
                                status_label: str,
                                category_label: str,
                                get_actual_players_func):
        """Check and report status for a specific category."""
        try:
            expected_players = set(server.get_players_by_label(category_label))
            actual_players = set(get_actual_players_func())

            missing_players = expected_players - actual_players
            extra_players = actual_players - expected_players

            if missing_players or extra_players:
                self.report_status_change(status_label, missing_players, extra_players)
        except Exception as e:
            logging.error(f"Error checking status for {status_label}: {e}")
            self.report("Error checking status", f"Error checking status for {status_label}: {e}")

    def report_status_change(self, status: str, missing_players: Set[str], extra_players: Set[str]):
        """Report changes in player status."""
        if missing_players:
            self.report("Players are missing", f"Missing {status} players: {', '.join(missing_players)}")
        if extra_players:
            self.report("Extra players", f"Unexpected {status} players: {', '.join(extra_players)}")
