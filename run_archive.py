import os
import schedule
import time
from archive.CSV_archiver import CSVService


def main():
    service = CSVService(
        config_file='service.json',
        output_dir=os.getenv('DSM_BACKUP_DIR', './csv_exports'),
        log_file='./csv_service.log'
    )
    service.run()


def schedule_service(interval):
    schedule.every(interval).hours.do(main)
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    main()
    #schedule_service(interval=24)
