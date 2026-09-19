import json
from typing import Dict


class ConfigManager:

    def __init__(self, config_path: str):
        self.path = config_path
        self._file = self.load_file()
        self._login = self._file["login"]
        self._url = self._file["url"]
        self._password = self._file["password"]
        self.interval = self._file["interval"]
        self.active = self._file["active"]
        self.admin = self._file["admin"]
        self.max_intervals = self._file["max_intervals"]

    def load_file(self):
        with open(self.path, "r", encoding="utf-8") as file:
            return json.load(file)

    def get_login(self) -> Dict[str, str]:
        return {
            "login": self._login,
            "url": self._url,
            "password": self._password
        }

    def get_config_data(self):
        return self._file
