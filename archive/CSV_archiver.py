import json
import os
from datetime import datetime
from util.repeat_logger import Logger
from processor.csv_generator import CSVTaskFactory


class CSVService:
    def __init__(self, config_file: str, output_dir: str, log_file: str):
        with open(config_file, 'r') as file:
            self.config = json.load(file)
        self.output_dir = output_dir
        self.logger = Logger(log_file).get_logger()

    def run(self):
        administrations = self.config['administrations']
        for admin in administrations:
            self.generate_all_csvs(admin)

    def generate_all_csvs(self, admin):
        name = admin['name']
        url = admin['url']
        login = admin['login']
        password = admin['password']

        csv_tasks = admin.get('csv_tasks', [])

        admin_dir = os.path.join(self.output_dir, name.split(' - ')[0])  # Take the first part of the name
        os.makedirs(admin_dir, exist_ok=True)

        date_str = datetime.now().strftime('%Y-%m-%d')
        date_dir_name = f"{date_str}-{name.split(' - ')[0]}"
        output_path = os.path.join(admin_dir, date_dir_name)

        os.makedirs(output_path, exist_ok=True)

        log_handler = self.logger

        for task_type in csv_tasks:
            try:
                task = CSVTaskFactory.create_task(
                    task_type, log_handler, url=url, login=login, password=password
                )
                output_file = os.path.join(output_path, f"{task_type}.csv")
                task.generate_csv(output_file)
                self.logger.info(f"Generated {output_file} for {name}")
            except Exception as e:
                self.logger.error(f"Failed to generate {task_type} for {name}: {e}")
