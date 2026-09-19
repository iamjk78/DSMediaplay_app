import logging
from logging.handlers import TimedRotatingFileHandler


class Logger:
    def __init__(self, log_file: str):
        self.logger = logging.getLogger("CSVServiceLogger")
        self.logger.setLevel(logging.DEBUG)
        handler = TimedRotatingFileHandler(log_file, when="midnight", interval=1)
        handler.suffix = "%Y-%m-%d"
        handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        self.logger.addHandler(handler)

    def get_logger(self):
        return self.logger
