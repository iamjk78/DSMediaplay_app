import os
import csv
from datetime import datetime
import json


class FileSaver:
    def __init__(self, base_dir: str, admin: str):
        self.base_dir = base_dir
        self.admin = admin
        self.base_path = self.create_directories()

    def create_directories(self):
        """Create the directory structure based on admin folder and current date."""
        now = datetime.now()
        admin_folder = os.path.join(self.base_dir, self.admin)
        date_folder = os.path.join(admin_folder, now.strftime("%Y-%m-%d"))

        os.makedirs(date_folder, exist_ok=True)
        return date_folder

    def save_to_csv(self, filename: str, data: set):
        """Save the provided data to a CSV file."""
        file_path = os.path.join(self.base_path, filename)
        with open(file_path, "w", newline='', encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            for item in data:
                writer.writerow([item])

    def backup_config(self, config_data: dict):
        """Create a backup of the current config file."""
        backup_path = os.path.join(self.base_path, f"config_backup_{datetime.now().strftime('%Y%m%d%H%M%S')}.json")
        with open(backup_path, "w", encoding="utf-8") as file:
            json.dump(config_data, file, indent=4)
