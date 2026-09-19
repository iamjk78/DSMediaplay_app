import os
import logging
from logging.handlers import RotatingFileHandler

from util.paths import log_dir as default_log_dir


class ServerLogger:
    def __init__(self, config=None, log_name="server"):
        """
        Initialize the ServerLogger with optional configuration.

        Parameters:
        - config (dict): A dictionary containing configuration values.
                         Expected keys are "server_log_path" and "log_level".
        - log_name (str): The name of the logger.
        """
        log_dir = config.get("server_log_path", os.getenv('SERVER_LOG_DIR', default_log_dir()))
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        log_file = os.path.join(log_dir, f"{log_name}.log")

        self.logger = logging.getLogger(log_name)
        self.logger.setLevel(config.get("log_level", logging.DEBUG))  # Default to DEBUG if not specified

        console_handler = logging.StreamHandler()
        file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=5)

        console_handler.setLevel(logging.INFO)
        file_handler.setLevel(logging.DEBUG)

        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)
        file_handler.setFormatter(formatter)

        if not self.logger.handlers:
            self.logger.addHandler(console_handler)
            self.logger.addHandler(file_handler)

    def get_logger(self):
        return self.logger
