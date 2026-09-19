import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time
import schedule
import time as time_module
from watchdog_service.config_processor import ConfigManager
from watchdog_service.watcher import PlayerStatusWatcher
from util.internet_com import StatusReporter
import logging
import os
import sys


class WatchManager:
    def __init__(self, config_path: str, log_dir: str):
        self.config = {}
        self.config_path = config_path
        self.log_dir = log_dir
        self.load_config()
        self.reporter = StatusReporter("email_config.json")
        self.executor = ThreadPoolExecutor(max_workers=len(self.config["watchers"]))
        self.threads = []
        self.initialize_logging()

    def initialize_logging(self):
        log_file = os.path.join(self.log_dir, 'watcher.log')
        logging.basicConfig(filename=log_file, level=logging.INFO,
                            format='%(asctime)s - %(levelname)s - %(message)s')

    def load_config(self):
        with open(self.config_path, "r", encoding="utf-8") as file:
            self.config = json.load(file)

    def start_watcher(self, cfg_path: str):
        cfg_manager = ConfigManager(cfg_path)
        watcher = PlayerStatusWatcher(cfg_manager, self.reporter)
        watcher.main_loop()

    def schedule_watchers(self):
        for watcher_config in self.config["watchers"]:
            cfg_path = watcher_config["config_path"]
            days = watcher_config["days"]
            start_time = time.fromisoformat(watcher_config["start_time"])
            end_time = time.fromisoformat(watcher_config["end_time"])
            # TODO: Fix the days as they are
            for day in days:
                schedule.every().day.at(watcher_config["start_time"]).do(
                    self.run_watcher, cfg_path, start_time, end_time
                ).tag(cfg_path)

    def run_watcher(self, cfg_path: str, start_time: time, end_time: time):
        now = datetime.now().time()
        if start_time <= now <= end_time:
            thread = threading.Thread(target=self.start_watcher, args=(cfg_path,))
            thread.start()
            self.threads.append(thread)

    def stop_watchers(self):
        for thread in self.threads:
            if thread.is_alive():
                thread.join()

    def run(self):
        self.schedule_watchers()
        while True:
            schedule.run_pending()
            time_module.sleep(1)


def main():
    if len(sys.argv) != 3:
        print("Usage: python watch_manager.py <config_path> <log_dir>")
        sys.exit(1)

    config_path = sys.argv[1]
    log_dir = sys.argv[2]

    watch_manager = WatchManager(config_path, log_dir)
    watch_manager.run()


if __name__ == "__main__":
    main()
