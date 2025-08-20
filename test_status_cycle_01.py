# test_status_cycle_01.py

import csv
import logging
import os
import time
import sys
import random
from datetime import datetime, timedelta  # Import both datetime and timedelta


# Configuration
CONFIG = {
    'recording_status_file': 'recording_status.txt',
    'log_file': os.path.join('logs', 'test_status_cycle_01.log'),
    'statuses': ['Initial', 'Idle', 'Recording', 'Cooldown', 'Processing', 'ProcessSuccess', 'ProcessFailure', 'Shutting Down'],
    'update_interval': 4.0  # Seconds between status changes, reduced for faster testing
}

def setup_logging(log_file):
    try:
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
            logging.info(f"Created log directory: {log_dir}")

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(threadName)s: %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        logger = logging.getLogger(__name__)
        logger.info(f"Logging initialized, writing to {log_file}")
        return logger
    except Exception as e:
        print(f"Failed to initialize logging: {e}")
        raise

logger = setup_logging(CONFIG['log_file'])

def write_status_file(status, file_path):
    try:
        with open(file_path, 'w', newline='') as f:
            writer = csv.DictWriter(
                f,
                fieldnames=['Status', 'Lat', 'Lon', 'Temp1', 'Temp2', 'Temp3', 'Temp4', 'Temp5', 'Offset'],
                quoting=csv.QUOTE_MINIMAL
            )
            writer.writeheader()
            offset = random.uniform(-240, 240) if status in ['ProcessSuccess', 'ProcessFailure'] else ''
            data = {
                'Status': status,
                'Lat': '53.151378833',
                'Lon': '-2.3712405',
                'Temp1': '25.0',
                'Temp2': '26.5',
                'Temp3': 'None',
                'Temp4': 'None',
                'Temp5': 'None',
                'Offset': f'{offset:.2f}' if offset else ''
            }
            writer.writerow(data)
            logger.info(f"Wrote status '{status}'")
            logger.debug(f"to  {file_path} with data: {data}")
    except Exception as e:
        logger.error(f"Error writing to {file_path}: {e}")

def write_test_accuracy_csv(file_path):
    with open(file_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['date', 'accuracy_seconds', 'time_hours'])
        writer.writeheader()
        today = datetime.now().date()
        for day in range(8):
            date = today - timedelta(days=day)
            for i in range(20):
                t = i * 1.2
                # Simulate realistic offsets (e.g., Gaussian distribution around 0)
                offset = random.gauss(0, 30) if random.random() < 0.9 else random.uniform(-240, 240)
                offset = min(max(offset, -240), 240)  # No +10 bias to match real data
                writer.writerow({
                    'date': date.strftime('%Y-%m-%d'),
                    'accuracy_seconds': offset,
                    'time_hours': t
                })
    logger.info(f"Wrote test data to {file_path}")

def main():
    file_path = os.path.join(os.path.dirname(__file__), CONFIG['recording_status_file'])
    statuses = CONFIG['statuses']
    update_interval = CONFIG['update_interval']
    write_test_accuracy_csv('accuracy.csv')

    logger.info(f"Waiting {update_interval} seconds before next status")
    
    if not os.path.exists(file_path):
        logger.info(f"Creating initial {file_path}")
        write_status_file(statuses[0], file_path)

    try:
        index = 0
        while True:
            status = statuses[index % len(statuses)]
            logger.debug(f"Preparing to update status to '{status}'")
            write_status_file(status, file_path)
            index += 1
            logger.debug(f"Waiting {update_interval} seconds before next status")
            time.sleep(update_interval)
    except KeyboardInterrupt:
        logger.info("Test program interrupted, exiting")
        write_status_file('Shutting Down', file_path)
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        write_status_file('Shutting Down', file_path)
        sys.exit(1)

if __name__ == "__main__":
    main()
