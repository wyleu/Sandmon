# gps_thread41.py

import queue
import threading
import logging
import time
import os
import csv
import datetime
import subprocess
import glob
import pyaudio
import wave
from gps3.agps3threaded import AGPS3mechanism
import uuid
from concurrent.futures import ThreadPoolExecutor
import colorlog

# Configuration
CONFIG = {
    'template_file': 'normalized_hour_strike_preamble.wav',
    'audio_format': pyaudio.paInt16,
    'valid_template_files': ['Duncan_hour.wav', 'normalized_hour_strike_preamble.wav'],
    'max_offset': 120,  # Half of record_duration (240 seconds)
    'channels': 1,
    'rate': 44100,
    'chunk': 1024,
    'record_duration': 4 * 60,  # seconds
    'gps_poll_interval': 3600,  # Static location, check hourly
    'global_trigger_cooldown': 10,  # Seconds
    'valid_lat_range': (-90, 90),
    'valid_lon_range': (-180, 180),
    'default_lat': "53.151378833",  # Cheshire, UK (church clock tower)
    'default_lon': "-2.3712405",
    'latest_recording_file': 'latest_recording.txt',
    'last_file_path': os.path.join('recordings', 'last_file'),
    'recording_status_file': 'recording_status.txt',
    'csv_columns': ['File', 'Lat', 'Lon', 'Temp1', 'Temp2', 'Temp3', 'Temp4', 'Temp5', 'Status', 'Offset', 'TestOffset'],
    'log_file': os.path.join('logs', f"{os.path.splitext(os.path.basename(__file__))[0]}.log"),
    'trigger_file': 'trigger_recording.txt',
    'trigger_check_interval': 5,
    'processing_module': "chunked_8.py",
    'max_queue_size': 50,
    'audio_init_retries': 3,
    'audio_init_delay': 2,
    'temperature_interval': 3600,  # Hourly temperature reads
}

# Logging setup
def setup_logging(log_file):
    try:
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
            logging.info(f"Created log directory: {log_dir}")

        # Colored formatter for console and colored log file
        colored_formatter = colorlog.ColoredFormatter(
            '%(log_color)s%(asctime)s - %(threadName)s: %(levelname)s - %(message)s',
            log_colors={
                'DEBUG': 'cyan',
                'INFO': 'green',
                'WARNING': 'yellow',
                'ERROR': 'red',
                'CRITICAL': 'red,bg_white',
            }
        )

        # Plain formatter for plain text log file
        plain_formatter = logging.Formatter(
            '%(asctime)s - %(threadName)s: %(levelname)s - %(message)s'
        )

        # Console handler
        stream_handler = colorlog.StreamHandler()
        stream_handler.setFormatter(colored_formatter)

        # Colored file handler
        colored_file_handler = logging.FileHandler(log_file)
        colored_file_handler.setFormatter(colored_formatter)

        # Plain file handler
        plain_log_file = log_file.replace('.log', '_plain.log')
        plain_file_handler = logging.FileHandler(plain_log_file)
        plain_file_handler.setFormatter(plain_formatter)

        # Configure logging
        logging.basicConfig(
            level=logging.INFO,
            handlers=[
                colored_file_handler,
                plain_file_handler,
                stream_handler
            ]
        )
        logger = logging.getLogger(__name__)
        logger.info(f"Logging initialized, writing to {log_file} (colored) and {plain_log_file} (plain)")
        return logger
    except Exception as e:
        print(f"Failed to initialize logging: {e} Line: {e.__traceback__.tb_lineno}")
        raise

logger = setup_logging(CONFIG['log_file'])

file_lock = threading.Lock()
trigger_lock = threading.Lock()
last_trigger_time = time.time()

def generate_message_id():
    return str(uuid.uuid4())

def initialize_csv_file(file_path, columns):
    if not os.path.exists(file_path):
        try:
            with open(file_path, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=columns, quoting=csv.QUOTE_MINIMAL)
                writer.writeheader()
            logger.info(f"Initialized CSV file: {file_path}")
        except Exception as e:
            logger.error(f"Error initializing CSV file {file_path}: {e} Line: {e.__traceback__.tb_lineno}")

class PeekableQueue:
    def __init__(self, maxsize=0):
        self._queue = queue.Queue(maxsize=maxsize)
        self._lock = threading.Lock()

    def put(self, item):
        with self._lock:
            if self._queue.qsize() >= self._queue.maxsize > 0:
                logger.warning("Queue full, discarding oldest message")
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
            self._queue.put(item)

    def get(self, timeout=None):
        with self._lock:
            if timeout is None:
                return self._queue.get()
            else:
                return self._queue.get(timeout=timeout)

    def peek(self):
        with self._lock:
            try:
                item = self._queue.get_nowait()
                self._queue.put(item)
                return item
            except queue.Empty:
                return None

    def qsize(self):
        with self._lock:
            return self._queue.qsize()

    def empty(self):
        with self._lock:
            return self._queue.empty()

    def clear_type(self, message_type, target):
        with self._lock:
            temp_queue = queue.Queue()
            removed_count = 0
            while not self._queue.empty():
                try:
                    item = self._queue.get_nowait()
                    if item.get("type") == message_type and item.get("target") == target:
                        removed_count += 1
                        logger.debug(f"Removed stale {message_type} message for {target}")
                    else:
                        temp_queue.put(item)
                except queue.Empty:
                    break
            while not temp_queue.empty():
                self._queue.put(temp_queue.get())
            return removed_count

class BaseThread:
    def __init__(self, name, shared_queue, max_retries=5, retry_delay=5):
        self.name = name
        self.shared_queue = shared_queue
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        logger.info(f"Starting {self.name} thread")
        self.thread.start()

    def stop(self):
        logger.info(f"Stopping {self.name} thread")
        message = {"id": generate_message_id(), "type": "STOP", "data": {}, "target": self.name}
        self.retry_on_failure(self.shared_queue.put, message)
        logger.info(f"Sent STOP message for {self.name}: {message}")

    def retry_on_failure(self, func, *args, **kwargs):
        for attempt in range(self.max_retries):
            try:
                result = func(*args, **kwargs)
                if func == self.shared_queue.put:
                    logger.debug(f"{self.name} added message to shared_queue, size: {self.shared_queue.qsize()}")
                return result
            except Exception as e:
                logger.error(f"Attempt {attempt+1} failed in {self.name}: {e} Line: {e.__traceback__.tb_lineno}")
                if attempt + 1 == self.max_retries:
                    logger.error(f"Max retries reached in {self.name} for {func.__name__}")
                    raise
                time.sleep(self.retry_delay)

    def handle_queue_message(self, message):
        """Handle messages, checking target field first and delegating to thread-specific handler."""
        target = message.get("target", self.name)
        if target not in [self.name, "ALL"]:
            logger.debug(f"Ignoring message for {target}, not matching {self.name}")
            return True

        logger.info(f"{self.name} processing message, type: {message.get('type')}, target: {target}, queue size: {self.shared_queue.qsize()}")
        message["consumed_by"] = self.name
        logger.debug(f"Processed message: {message}")

        # Handle common STOP message
        if message["type"] == "STOP":
            logger.info(f"{self.name} thread shutting down")
            self.cleanup()
            return False

        # Delegate to thread-specific handler
        return self.handle_thread_message(message)

    def handle_thread_message(self, message):
        """Thread-specific message handler (to be implemented by subclasses)."""
        raise NotImplementedError("Subclasses must implement handle_thread_message method")

    def cleanup(self):
        """Thread-specific cleanup method (to be implemented by subclasses if needed)."""
        pass

    def process_thread_specifics(self):
        pass

    def run(self):
        logger.info(f"{self.name} started as {threading.current_thread().name}")
        while True:
            try:
                message = self.shared_queue.peek()
                if message and message.get("target") in [self.name, "ALL"]:
                    message = self.shared_queue.get()
                    if not self.handle_queue_message(message):
                        break
                else:
                    self.process_thread_specifics()
                    time.sleep(0.001)
            except Exception as e:
                logger.error(f"Error in {self.name} run loop: {e} Line: {e.__traceback__.tb_lineno}")
                time.sleep(0.005)

class GPS3ListenerThread(BaseThread):
    def __init__(self, shared_queue):
        super().__init__("GPS3Listener", shared_queue)
        self.last_trigger_content = ""
        self.agps_thread = None
        self.temperatures = ["None"] * 5
        self.timer = None
        self.recording_in_progress = False
        self.last_trigger_hour = -1
        self.last_gps_update_time = 0
        self.last_trigger_mtime = 0
        self.last_temperature_time = 0
        self.initialize_gps()
        self.start_hourly_timer()

    def _check_trigger_file(self):
        """Check and process the trigger file to initiate a recording."""
        try:
            if not self._check_trigger_file_exists():
                return

            content = self._read_trigger_file_content()
            if not self._validate_trigger_content(content):
                return

            mtime = self._check_trigger_mtime()
            if mtime is None:
                return

            self.last_trigger_content = content
            self.last_trigger_mtime = mtime

            test_mode = self._parse_test_mode_parameters(content)
            if test_mode is False:  # Validation failed
                return

            message = self._build_trigger_message(test_mode)
            self._send_trigger_message(message)
            self._clear_trigger_file()
        except Exception as e:
            logger.error(f"Error checking trigger file: {e} Line: {e.__traceback__.tb_lineno}")

    def _check_trigger_file_exists(self):
        """Check if the trigger file exists."""
        if not os.path.exists(CONFIG['trigger_file']):
            return False
        return True

    def _read_trigger_file_content(self):
        """Read the content of the trigger file."""
        try:
            with open(CONFIG['trigger_file'], 'r') as f:
                content = f.read().strip()
            return content
        except Exception as e:
            logger.error(f"Error reading trigger file: {e} Line: {e.__traceback__.tb_lineno}")
            return ''

    def _validate_trigger_content(self, content):
        """Validate that the trigger file content is valid and changed."""
        if not content.lower().startswith("record"):
            logger.debug(f"Trigger file content '{content}' does not start with 'Record', ignoring")
            return False
        if content == self.last_trigger_content:
            logger.debug("Trigger file content unchanged, ignoring")
            return False
        return True

    def _check_trigger_mtime(self):
        """Check if the trigger file's modification time allows a new trigger."""
        try:
            mtime = os.path.getmtime(CONFIG['trigger_file'])
            if not self._is_trigger_allowed(mtime):
                return None
            return mtime
        except Exception as e:
            logger.error(f"Error getting trigger file mtime: {e} Line: {e.__traceback__.tb_lineno}")
            return None

    def _parse_test_mode_parameters(self, content):
        """Parse and validate test mode parameters from the trigger file content."""
        parts = content.split(',')
        if len(parts) == 1:  # No test mode parameters
            return None

        if len(parts) != 4:
            logger.error(f"Invalid trigger file format: {content}, expected 'Record' or 'Record,template_file,percentage,offset'")
            return False

        try:
            template_file = parts[1].strip()
            percentage = float(parts[2].strip())
            offset = float(parts[3].strip())

            if template_file not in CONFIG['valid_template_files']:
                logger.error(f"Invalid template file: {template_file}, must be one of {CONFIG['valid_template_files']}")
                return False
            if not os.path.exists(template_file):
                logger.error(f"Template file not found: {template_file}")
                return False
            if not (0 < percentage <= 1):
                logger.error(f"Invalid percentage: {percentage}, must be between 0 and 1")
                return False
            if abs(offset) > CONFIG['max_offset']:
                logger.error(f"Invalid offset: {offset}, must be between -{CONFIG['max_offset']} and +{CONFIG['max_offset']}")
                return False

            test_mode = {
                "template_file": template_file,
                "percentage": percentage,
                "offset": offset
            }
            logger.info(f"Test mode parameters: template={template_file}, percentage={percentage}, offset={offset}")
            return test_mode
        except ValueError as e:
            logger.error(f"Error parsing test mode parameters: {e}")
            return False

    def _build_trigger_message(self, test_mode):
        """Build the TRIGGER_RECORDING message with optional test_mode data."""
        now = datetime.datetime.now()
        lat, lon = self.validate_gps_data(
            getattr(self.agps_thread.data_stream, 'lat', 'n/a'),
            getattr(self.agps_thread.data_stream, 'lon', 'n/a')
        )
        self.read_temperatures()
        message = {
            "id": generate_message_id(),
            "type": "TRIGGER_RECORDING",
            "data": {
                "time": now.astimezone().isoformat(),
                "lat": lat,
                "lon": lon,
                "temperatures": self.temperatures,
                "source": "file_trigger"
            },
            "target": "AudioRecorder"
        }
        if test_mode:
            message["data"]["test_mode"] = test_mode
        return message

    def _send_trigger_message(self, message):
        """Send the TRIGGER_RECORDING message to the shared queue."""
        self.retry_on_failure(self.shared_queue.put, message)
        logger.info(f"Trigger file detected, sent TRIGGER_RECORDING: {message}, queue size: {self.shared_queue.qsize()}")

    def _clear_trigger_file(self):
        """Clear the trigger file content."""
        try:
            with file_lock:
                with open(CONFIG['trigger_file'], 'w') as f:
                    f.write('')
                logger.debug("Cleared trigger file content")
        except Exception as e:
            logger.error(f"Error clearing trigger file: {e} Line: {e.__traceback__.tb_lineno}") 
           
    def initialize_gps(self):
        try:
            self.agps_thread = AGPS3mechanism()
            self.agps_thread.stream_data(host='localhost', port=2947)
            self.agps_thread.run_thread()
            logger.info("GPS3 threaded listener started on localhost:2947")
            time.sleep(1)  # Wait for initial data
            lat = getattr(self.agps_thread.data_stream, 'lat', 'n/a')
            lon = getattr(self.agps_thread.data_stream, 'lon', 'n/a')
            logger.info(f"Initial GPS data: lat={lat}, lon={lon}")
            if lat == 'n/a' or lon == 'n/a':
                logger.warning(f"Penalized for 'n/a' values, using defaults: {CONFIG['default_lat']}, {CONFIG['default_lon']}")
        except Exception as e:
            logger.error(f"Error initializing GPS: {e} Line: {e.__traceback__.tb_lineno}")
      
    def start_hourly_timer(self):
        try:
            now = datetime.datetime.now()
            next_hour = now.hour + 1 if now.minute < 58 else now.hour + 2
            next_hour = next_hour % 24
            next_datetime = now.replace(hour=next_hour, minute=0, second=0, microsecond=0)
            next_datetime -= datetime.timedelta(minutes=2)
            if next_hour <= now.hour and now.hour >= 23:
                next_datetime += datetime.timedelta(days=1)
            wait_time = (next_datetime - now).total_seconds()
            while wait_time <= 0:
                logger.warning(f"Invalid wait_time {wait_time}, rescheduling for next hour")
                next_hour = (next_hour + 1) % 24
                next_datetime = now.replace(hour=next_hour, minute=0, second=0, microsecond=0)
                next_datetime -= datetime.timedelta(minutes=2)
                if next_hour == 0:
                    next_datetime += datetime.timedelta(days=1)
                wait_time = (next_datetime - now).total_seconds()
            logger.info(f"Scheduling hourly recording in {wait_time:.2f} seconds for {next_datetime}")
            if self.timer is not None and self.timer.is_alive():
                logger.debug("Existing timer still active, canceling and rescheduling")
                self.timer.cancel()
            self.timer = threading.Timer(wait_time, self.send_hourly_trigger)
            self.timer.start()
            logger.debug(f"Timer scheduled: is_alive={self.timer.is_alive()}")
        except Exception as e:
            logger.error(f"Error in start_hourly_timer: {e} Line: {e.__traceback__.tb_lineno}")
            self.timer = threading.Timer(60, self.start_hourly_timer)
            self.timer.start()
            logger.info("Retrying timer scheduling in 60 seconds")

    def cleanup(self):
        """Cleanup resources for GPS3ListenerThread."""
        if self.timer:
            self.timer.cancel()
        if self.agps_thread:
            self.agps_thread.stop()
        logger.info("GPS3Listener cleanup completed")

    def send_hourly_trigger(self):
        with trigger_lock:
            current_time = time.time()
            if current_time - self.last_trigger_hour * 3600 < 3500:  # Less than ~58 minutes since last trigger
                logger.warning(f"Ignoring hourly trigger, too soon since last trigger at {self.last_trigger_hour}:00")
                self.start_hourly_timer()  # Still reschedule for next hour
                return
            if self.recording_in_progress:
                logger.warning(f"Hourly trigger blocked: recording_in_progress={self.recording_in_progress}. Resetting.")
                self.recording_in_progress = False
                self.start_hourly_timer()
                return
        now = datetime.datetime.now()
        lat, lon = self.validate_gps_data(
            getattr(self.agps_thread.data_stream, 'lat', 'n/a'),
            getattr(self.agps_thread.data_stream, 'lon', 'n/a')
        )
        self.read_temperatures()
        dict_status = {
            "id": generate_message_id(),
            "type": "TRIGGER_RECORDING",
            "data": {
                "time": now.astimezone().isoformat(),
                "lat": lat,
                "lon": lon,
                "temperatures": self.temperatures,
                "source": "hourly"
            },
            "target": "AudioRecorder"
        }
        self.retry_on_failure(self.shared_queue.put, dict_status)
        logger.info(f"Hourly TRIGGER_RECORDING sent: {dict_status}, queue size: {self.shared_queue.qsize()}")
        self.last_trigger_hour = now.hour
        self.start_hourly_timer()

    def validate_gps_data(self, lat, lon):
        try:
            lat = float(lat) if isinstance(lat, (int, float, str)) else None
            lon = float(lon) if isinstance(lon, (int, float, str)) else None
            if (lat is None or lon is None or
                not (CONFIG['valid_lat_range'][0] <= lat <= CONFIG['valid_lat_range'][1]) or
                not (CONFIG['valid_lon_range'][0] <= lon <= CONFIG['valid_lon_range'][1])):
                logger.warning(f"Invalid GPS data: lat={lat}, lon={lon}, using defaults: {CONFIG['default_lat']}, {CONFIG['default_lon']}")
                return CONFIG['default_lat'], CONFIG['default_lon']
            return lat, lon
        except Exception as e:
            logger.error(f"Error validating GPS data: {e}, using defaults: {CONFIG['default_lat']}, {CONFIG['default_lon']}")
            return CONFIG['default_lat'], CONFIG['default_lon']

    def read_temperatures(self):
        base_dir = '/sys/bus/w1/devices/'
        try:
            device_folders = glob.glob(base_dir + '10*')[:5]
            logger.info(f"Found {len(device_folders)} OneWire devices: {device_folders}")
            if not device_folders:
                logger.error("No OneWire devices found")
                self.temperatures = ["None"] * 5
                return

            temp_values = ["None"] * 5
            for i, device_folder in enumerate(device_folders):
                device_id = os.path.basename(device_folder)
                device_file = device_folder + '/w1_slave'
                logger.debug(f"Reading sensor: {device_id}, file: {device_file}")
                if not os.path.exists(device_file):
                    logger.error(f"Sensor file not found: {device_file}")
                    temp_values[i] = "None"
                    continue

                lines = self.read_temp_raw(device_file, device_id)
                if not lines or len(lines) < 2:
                    logger.warning(f"Failed to read raw temp for {device_id}")
                    temp_values[i] = "None"
                    continue

                retry_count = 0
                while lines[0].strip()[-3:] != 'YES' and retry_count < 3:
                    time.sleep(0.2)
                    lines = self.read_temp_raw(device_file, device_id)
                    retry_count += 1
                if lines[0].strip()[-3:] != 'YES':
                    logger.error(f"Invalid CRC for {device_id}")
                    temp_values[i] = "None"
                    continue

                equals_pos = lines[1].find('t=')
                if equals_pos != -1:
                    temp_string = lines[1][equals_pos+2:].strip()
                    try:
                        temp_c = float(temp_string) / 1000.0
                        temp_values[i] = f"{temp_c:.1f}"
                    except ValueError:
                        logger.error(f"Invalid temperature data for {device_id}")
                        temp_values[i] = "None"
                else:
                    temp_values[i] = "None"

            self.temperatures = temp_values
            logger.info(f"Updated temperatures: {self.temperatures}")
        except Exception as e:
            logger.error(f"Error reading OneWire sensors: {e} Line: {e.__traceback__.tb_lineno}")
            self.temperatures = ["None"] * 5

    def read_temp_raw(self, device_file, device_id):
        try:
            with open(device_file, 'r') as f:
                return f.readlines()
        except Exception as e:
            logger.error(f"Error reading raw temp for {device_id}: {e} Line: {e.__traceback__.tb_lineno}")
            return []

    def handle_thread_message(self, message):
        """Handle thread-specific messages for GPS3ListenerThread."""
        if message["type"] == "RECORDING_STATUS":
            old_status = self.recording_in_progress
            self.recording_in_progress = message["data"]["is_recording"]
            logger.info(f"Updated recording status from {old_status} to {self.recording_in_progress}")
            return True
        logger.warning(f"Unhandled message type: {message.get('type')} for {self.name}")
        return True

    def process_thread_specifics(self):
        if self.timer is None or not self.timer.is_alive():
            logger.warning("No active timer found, rescheduling")
            self.start_hourly_timer()
        self._check_trigger_file()
        self._update_gps_and_temperatures()
        self._sleep()

    def _read_trigger_file_content(self):
        """Read and return the content of the trigger file."""
        with open(CONFIG['trigger_file'], 'r') as f:
            return f.read().strip()

    def _is_trigger_allowed(self, mtime):
        with trigger_lock:
            if mtime <= self.last_trigger_mtime:
                logger.debug(f"Trigger file not modified: mtime={mtime}, last_mtime={self.last_trigger_mtime}")
                return False
            return True

    def _send_trigger_recording_message(self, mtime):
        self.last_trigger_mtime = mtime
        now = datetime.datetime.now()
        lat, lon = self.validate_gps_data(
            getattr(self.agps_thread.data_stream, 'lat', 'n/a'),
            getattr(self.agps_thread.data_stream, 'lon', 'n/a')
        )
        self.read_temperatures()
        message = {
            "id": generate_message_id(),
            "type": "TRIGGER_RECORDING",
            "data": {
                "time": now.astimezone().isoformat(),
                "lat": lat,
                "lon": lon,
                "temperatures": self.temperatures,
                "source": "file_trigger"
            },
            "target": "AudioRecorder"
        }
        self.retry_on_failure(self.shared_queue.put, message)
        logger.info(f"Trigger file detected with content 'Record', sent TRIGGER_RECORDING: {message}, queue size: {self.shared_queue.qsize()}")
        with file_lock:
            with open(CONFIG['trigger_file'], 'w') as f:
                f.write('')

    def _update_gps_and_temperatures(self):
        """Update GPS and temperature data hourly and send GPS_UPDATE message."""
        current_time = time.time()
        if current_time - self.last_gps_update_time < CONFIG['gps_poll_interval']:
            return

        lat = getattr(self.agps_thread.data_stream, 'lat', 'n/a')
        lon = getattr(self.agps_thread.data_stream, 'lon', 'n/a')
        lat, lon = self.validate_gps_data(lat, lon)
        if current_time - self.last_temperature_time >= CONFIG['temperature_interval']:
            self.read_temperatures()
            self.last_temperature_time = current_time
        message = {
            'id': generate_message_id(),
            'type': 'GPS_UPDATE',
            'data': {
                'lat': lat,
                'lon': lon,
                'time': datetime.datetime.now().astimezone().isoformat(),
                'temperatures': self.temperatures
            },
            'target': "AudioRecorder"
        }
        self.retry_on_failure(self.shared_queue.put, message)
        logger.debug(f"Sent GPS_UPDATE: {message}")
        self.last_gps_update_time = current_time

    def _sleep(self):
        """Sleep for the configured trigger check interval."""
        time.sleep(CONFIG['trigger_check_interval'])

class AudioRecorderThread(BaseThread):
    def __init__(self, shared_queue):
        super().__init__("AudioRecorder", shared_queue)
        self.pending_row_data = None
        self.no_fix = False
        self.last_gps_data = {"lat": CONFIG['default_lat'], "lon": CONFIG['default_lon'], "time": "n/a", "temperatures": ["None"] * 5}
        self.is_recording = False
        self.cooldown_timer = None
        self.current_state = "Initial"
        self.state_transitions = {
            "Initial": ["Idle"],
            "Idle": ["Recording", "Shutting Down", "Cooldown"],
            "Recording": ["Cooldown", "Shutting Down"],
            "Cooldown": ["Processing", "Idle", "Shutting Down"],
            "Processing": ["ProcessSuccess", "ProcessFailure", "NoMatch", "Shutting Down"],
            "ProcessSuccess": ["Idle", "Shutting Down"],
            "ProcessFailure": ["Idle", "Shutting Down"],
            "NoMatch": ["Idle", "Shutting Down"],
            "Shutting Down": []
        }
        self.initialize_status_file()
        time.sleep(5)  # Delay 5 seconds to allow Initial status to be displayed
        self.update_status_file("Idle")

    def initialize_status_file(self):
        """Initialize recording_status.txt with 'Initial' status."""
        try:
            with file_lock:
                with open(CONFIG['recording_status_file'], "w", newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=['Status', 'Lat', 'Lon', 'Temp1', 'Temp2', 'Temp3', 'Temp4', 'Temp5', 'Offset'], quoting=csv.QUOTE_MINIMAL)
                    writer.writeheader()
                    writer.writerow({
                        'Status': 'Initial',
                        'Lat': CONFIG['default_lat'],
                        'Lon': CONFIG['default_lon'],
                        'Temp1': self.last_gps_data['temperatures'][0],
                        'Temp2': self.last_gps_data['temperatures'][1],
                        'Temp3': self.last_gps_data['temperatures'][2],
                        'Temp4': self.last_gps_data['temperatures'][3],
                        'Temp5': self.last_gps_data['temperatures'][4],
                        'Offset': ''
                    })
                logger.info(f"Initialized {CONFIG['recording_status_file']} with status 'Initial', temperatures: {self.last_gps_data['temperatures']}")
        except Exception as e:
            logger.error(f"Error initializing {CONFIG['recording_status_file']}: {e} Line: {e.__traceback__.tb_lineno}")

    def update_status_file(self, status):
        if status not in self.state_transitions:
            logger.error(f"Invalid state: {status}")
            return False
        if status not in self.state_transitions[self.current_state] and status != self.current_state:
            # Allow self-transitions for Idle and Shutting Down
            if status not in ['Idle', 'Shutting Down']:
                logger.error(f"Invalid state transition from {self.current_state} to {status}")
                return False
        try:
            with file_lock:
                with open(CONFIG['recording_status_file'], "w", newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=['Status', 'Lat', 'Lon', 'Temp1', 'Temp2', 'Temp3', 'Temp4', 'Temp5', 'Offset'], quoting=csv.QUOTE_MINIMAL)
                    writer.writeheader()
                    data = self.pending_row_data if self.pending_row_data else {
                        'File': '',
                        'Lat': str(self.last_gps_data.get("lat", CONFIG['default_lat'])),
                        'Lon': str(self.last_gps_data.get("lon", CONFIG['default_lon'])),
                        'Temp1': self.last_gps_data['temperatures'][0],
                        'Temp2': self.last_gps_data['temperatures'][1],
                        'Temp3': self.last_gps_data['temperatures'][2],
                        'Temp4': self.last_gps_data['temperatures'][3],
                        'Temp5': self.last_gps_data['temperatures'][4],
                        'Status': status,
                        'Offset': ''
                    }
                    data['Status'] = status
                    writer.writerow({
                        'Status': data['Status'],
                        'Lat': data['Lat'],
                        'Lon': data['Lon'],
                        'Temp1': data.get('Temp1', 'None'),
                        'Temp2': data.get('Temp2', 'None'),
                        'Temp3': data.get('Temp3', 'None'),
                        'Temp4': data.get('Temp4', 'None'),
                        'Temp5': data.get('Temp5', 'None'),
                        'Offset': data.get('Offset', '')
                    })
                self.current_state = status
                logger.info(f"Updated recording_status.txt to status: {status}, data: {data}")
                return True
        except Exception as e:
            logger.error(f"Error updating {CONFIG['recording_status_file']}: {e} Line: {e.__traceback__.tb_lineno}")
            return False

    def start_cooldown_timer(self):
        """Start a timer to set 'Cooldown' status for the global cooldown period."""
        if self.cooldown_timer and self.cooldown_timer.is_alive():
            logger.debug("Existing cooldown timer still active, cancelling")
            self.cooldown_timer.cancel()

        self.update_status_file("Cooldown")
        self.cooldown_timer = threading.Timer(CONFIG['global_trigger_cooldown'], self.end_cooldown)
        self.cooldown_timer.start()
        logger.info(f"Started cooldown timer for {CONFIG['global_trigger_cooldown']} seconds")

    def end_cooldown(self):
        """End the cooldown period and transition to 'Idle' unless another status is active."""
        if self.is_recording:
            logger.debug("Cooldown ended but recording in progress, skipping Idle transition")
            return
        self.update_status_file("Idle")
        logger.info("Cooldown period ended, transitioned to Idle")

    def cleanup(self):
        """Cleanup resources for AudioRecorderThread."""
        if self.cooldown_timer:
            self.cooldown_timer.cancel()
        self.update_status_file("Shutting Down")
        logger.info("AudioRecorder cleanup completed")

    def check_recording_allowed(self, message):
        global last_trigger_time
        with trigger_lock:
            current_time = time.time()
            if self.is_recording:
                logger.warning(f"Ignoring TRIGGER_RECORDING while recording in progress")
                return False
            if current_time - last_trigger_time < CONFIG['global_trigger_cooldown']:
                logger.warning(f"Ignoring TRIGGER_RECORDING due to cooldown, LTT:{last_trigger_time} remaining={CONFIG['global_trigger_cooldown'] - (current_time - last_trigger_time):.1f}s")
                return False
            logger.info(f"Recording allowed: source={message['data']['source']}, time_since_last_trigger={(current_time - last_trigger_time):.1f}s")
            last_trigger_time = current_time
            return True

    def prepare_recording(self, message):
        output_dir = os.path.dirname(CONFIG['last_file_path'])
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            logger.info(f"Created base output directory: {output_dir}")

        date_str = datetime.datetime.now().strftime('%Y%m%d')
        date_dir = os.path.join(output_dir, date_str)
        if not os.path.exists(date_dir):
            os.makedirs(date_dir)
            logger.info(f"Created date-stamped directory: {date_dir}")

        output_file = os.path.join(
            date_dir,
            'recording_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S') + '.wav'
        )
        self.pending_row_data = {
            'File': output_file,
            'Lat': str(message['data']['lat']),
            'Lon': str(message['data']['lon']),
            'Temp1': message['data']['temperatures'][0] if len(message['data']['temperatures']) > 0 else 'None',
            'Temp2': message['data']['temperatures'][1] if len(message['data']['temperatures']) > 1 else 'None',
            'Temp3': message['data']['temperatures'][2] if len(message['data']['temperatures']) > 2 else 'None',
            'Temp4': message['data']['temperatures'][3] if len(message['data']['temperatures']) > 3 else 'None',
            'Temp5': message['data']['temperatures'][4] if len(message['data']['temperatures']) > 4 else 'None',
            'Status': 'Recording',
            'Offset': '',
            'TestOffset': str(message['data'].get('test_mode', {}).get('offset', '')),
            'test_mode': message['data'].get('test_mode', {})  # Store full test_mode
        }
        logger.info(f"Preparing to record to {output_file}")
        logger.debug(f"with data: {self.pending_row_data}")
        return output_file

    def initialize_audio_stream(self):
        """Initialize PyAudio stream with retries."""
        p = None
        stream = None
        for attempt in range(CONFIG['audio_init_retries']):
            try:
                p = pyaudio.PyAudio()
                stream = p.open(
                    format=CONFIG['audio_format'],
                    channels=CONFIG['channels'],
                    rate=CONFIG['rate'],
                    input=True,
                    frames_per_buffer=CONFIG['chunk']
                )
                logger.info("PyAudio stream opened successfully")
                return p, stream
            except Exception as e:
                logger.error(f"Failed to initialize PyAudio, attempt {attempt+1}: {e} Line: {e.__traceback__.tb_lineno}")
                if p:
                    p.terminate()
                if attempt + 1 < CONFIG['audio_init_retries']:
                    time.sleep(CONFIG['audio_init_delay'])
        logger.error("Max retries reached for PyAudio initialization")
        return None, None

    def record_audio(self, output_file, p, stream):
        """Record audio and inject template signal if in test mode."""
        try:
            params = self._setup_recording_params(output_file)
            template_info = self._load_template_signal(params['sample_rate'])
            frames = self._capture_audio_frames(stream, params['total_samples'])
            audio_data = self._process_audio_data(frames, params['total_samples'])
            audio_data = self._inject_template_signal(audio_data, template_info, params['total_samples'])
            self._save_audio_file(output_file, p, audio_data, params['sample_rate'])
            return True
        except Exception as e:
            logger.error(f"Error during recording: {e} Line: {e.__traceback__.tb_lineno}")
            return False

    def _setup_recording_params(self, output_file):
        """Initialize recording parameters and log setup."""
        record_duration = CONFIG['record_duration']  # 240 seconds
        sample_rate = CONFIG['rate']  # 44100 Hz
        total_samples = int(record_duration * sample_rate)
        logger.info(f"Recording for {record_duration} seconds to {output_file}")
        return {
            'record_duration': record_duration,
            'sample_rate': sample_rate,
            'total_samples': total_samples
        }

    def _load_template_signal(self, sample_rate):
        """Load and validate template signal for test mode."""
        import soundfile as sf

        test_mode = 'TestOffset' in self.pending_row_data and self.pending_row_data['TestOffset'] != ''
        template_data = None
        template_samples = 0
        offset_samples = 0
        percentage = 0
        template_file = None

        if test_mode:
            test_mode_data = self.pending_row_data.get('test_mode', {})
            template_file = test_mode_data.get('template_file')
            percentage = float(test_mode_data.get('percentage', 0))
            offset = float(self.pending_row_data['TestOffset'])
            try:
                template_data, template_rate = sf.read(template_file)
                if template_rate != sample_rate:
                    logger.error(f"Template sample rate {template_rate} does not match recording rate {sample_rate}")
                    return None
                template_samples = len(template_data)
                offset_samples = int(offset * sample_rate)  # Convert offset to samples
                logger.info(f"Test mode: injecting {template_file} at {percentage*100}% amplitude, offset {offset} seconds ({offset_samples} samples)")
            except Exception as e:
                logger.error(f"Error loading template file {template_file}: {e} Line: {e.__traceback__.tb_lineno}")
                return None

        return {
            'test_mode': test_mode,
            'template_data': template_data,
            'template_samples': template_samples,
            'offset_samples': offset_samples,
            'percentage': percentage,
            'template_file': template_file
        }

    def _capture_audio_frames(self, stream, total_samples):
        """Capture audio frames using PyAudio stream."""
        frames = []
        recorded_samples = 0
        while recorded_samples < total_samples:
            try:
                data = stream.read(CONFIG['chunk'], exception_on_overflow=False)
                frames.append(data)
                recorded_samples += CONFIG['chunk']
            except Exception as e:
                logger.error(f"Error reading audio stream: {e} Line: {e.__traceback__.tb_lineno}")
                break
        return frames

    def _process_audio_data(self, frames, total_samples):
        """Convert recorded frames to a writable NumPy array."""
        import numpy as np
        audio_data = np.frombuffer(b''.join(frames), dtype=np.int16).copy()  # Create writable copy
        if len(audio_data) > total_samples:
            audio_data = audio_data[:total_samples]
        return audio_data

    def _inject_template_signal(self, audio_data, template_info, total_samples):
        """Inject template signal into audio data for test mode."""
        if not template_info['test_mode'] or template_info['template_data'] is None:
            return audio_data

        import numpy as np
        template_data = (template_info['template_data'] * template_info['percentage']).astype(np.int16)  # Scale amplitude
        start_sample = max(0, int(total_samples / 2 + template_info['offset_samples']))  # Center + offset
        end_sample = min(total_samples, start_sample + template_info['template_samples'])
        template_end = min(template_info['template_samples'], total_samples - start_sample)
        if template_end > 0:
            audio_data[start_sample:end_sample] += template_data[:template_end]
            logger.info(f"Injected template signal from sample {start_sample} to {end_sample}")
        else:
            logger.warning("Template signal not injected: offset out of bounds or template too long")
        return audio_data

    def _save_audio_file(self, output_file, p, audio_data, sample_rate):
        """Save audio data to a WAV file."""
        wf = wave.open(output_file, 'wb')
        wf.setnchannels(CONFIG['channels'])
        wf.setsampwidth(p.get_sample_size(CONFIG['audio_format']))
        wf.setframerate(sample_rate)
        wf.writeframes(audio_data.tobytes())
        wf.close()
        logger.info(f"Recording saved to {output_file}")

    def trigger_processing(self, output_file, test_mode=None):
        """Send TRIGGER_PROCESSING message to ProcessingThread."""
        message_process = {
            "id": generate_message_id(),
            "type": "TRIGGER_PROCESSING",
            "data": {
                "output_file": output_file,
                "last_file_path": CONFIG['last_file_path'],
                "test_mode": test_mode
            },
            "target": "ProcessingThread"
        }
        self.retry_on_failure(self.shared_queue.put, message_process)
        logger.info(f"Sent TRIGGER_PROCESSING for file: {output_file}, test_mode: {test_mode}")

    def update_recording_status(self, is_recording):
        """Update recording status and notify GPS3Listener."""
        self.is_recording = is_recording
        message_status = {
            "id": generate_message_id(),
            "type": "RECORDING_STATUS",
            "data": {"is_recording": is_recording},
            "target": "GPS3Listener"
        }
        self.retry_on_failure(self.shared_queue.put, message_status)
        self.update_status_file('Recording' if is_recording else 'Idle')
        logger.info(f"Recording status updated to: {'Recording' if is_recording else 'Idle'}")

    def handle_thread_message(self, message):
        """Handle thread-specific messages for AudioRecorderThread."""
        if message["type"] == "TRIGGER_RECORDING":
            self.shared_queue.clear_type("TRIGGER_RECORDING", "AudioRecorder")
            return self.handle_trigger_recording(message)
        elif message["type"] == "GPS_UPDATE":
            self.last_gps_data = message["data"]
            logger.info(f"Updated GPS data: {self.last_gps_data}")
            self.update_status_file("Idle")
            return True
        elif message["type"] == "PROCESSING_START":
            self.update_status_file("Processing")
            logger.info(f"Received PROCESSING_START, updated status to Processing")
            return True
        elif message["type"] == "PROCESSING_COMPLETE":
            return self.handle_processing_complete(message)
        logger.warning(f"Unhandled message type: {message.get('type')} for {self.name}")
        return True

    def handle_trigger_recording(self, message):
        """Handle TRIGGER_RECORDING message and start cooldown after recording."""
        if not self.check_recording_allowed(message):
            return True

        self.update_recording_status(True)
        output_file = self.prepare_recording(message)
        p, stream = self.initialize_audio_stream()

        try:
            if not stream:
                logger.error("Audio stream initialization failed, aborting recording")
                return True

            success = self.record_audio(output_file, p, stream)
            if success:
                self.trigger_processing(output_file, test_mode=message['data'].get('test_mode'))
            else:
                logger.error("Recording failed, not triggering processing")
        except Exception as e:
            logger.error(f"Exception during recording: {e} Line: {e.__traceback__.tb_lineno}")
        finally:
            if stream:
                stream.stop_stream()
                stream.close()
            if p:
                p.terminate()
            self.update_recording_status(False)
            self.start_cooldown_timer()

        return True

    def handle_processing_complete(self, message):
        if not self.pending_row_data:
            logger.error("No pending_row_data available for PROCESSING_COMPLETE, skipping status update")
            self.update_status_file('Idle')
            return True
        try:
            offset = message['data'].get('offset', 'argument')
            status = message['data'].get('status', 'error')
            if status == "success":
                self.pending_row_data['Offset'] = offset
                new_state = 'ProcessSuccess'
                try:
                    analysis_offset = float(offset)
                    if 'TestOffset' in self.pending_row_data and self.pending_row_data['TestOffset'] != '':
                        test_offset = float(self.pending_row_data['TestOffset'])
                        offset_diff = abs(analysis_offset - test_offset)
                        logger.info(f"Test mode comparison: analysis_offset={analysis_offset}, test_offset={test_offset}, difference={offset_diff}")
                        if offset_diff > 1.0:  # 1-second tolerance
                            logger.warning(f"Large offset difference: {offset_diff} seconds")
                except (ValueError, TypeError):
                    logger.error(f"Invalid offset value: {offset}")
                    new_state = 'ProcessFailure'
                    self.pending_row_data['Offset'] = 'Invalid Offset'
            elif status == "no_match":
                new_state = 'NoMatch'
                self.pending_row_data['Offset'] = 'No Match'
                logger.info("Processing resulted in no match due to similar RMS values")
            else:  # status == "error"
                new_state = 'ProcessFailure'
                self.pending_row_data['Offset'] = 'Invalid Offset'
                logger.error(f"Processing failed with status: {status}, offset: {offset}")
            self.pending_row_data['Status'] = new_state
            # Create a copy of pending_row_data with only the fields in csv_columns
            csv_row_data = {key: self.pending_row_data.get(key, '') for key in CONFIG['csv_columns']}
            with file_lock:
                for file_path in [CONFIG['latest_recording_file'], CONFIG['last_file_path']]:
                    try:
                        with open(file_path, 'a', newline='') as f:
                            writer = csv.DictWriter(f, fieldnames=CONFIG['csv_columns'])
                            writer.writerow(csv_row_data)
                        logger.info(f"Appended row to {file_path}: {csv_row_data}")
                    except Exception as e:
                        logger.error(f"Failed to write to {file_path}: {e} Line: {e.__traceback__.tb_lineno}")
            self.pending_row_data = None
            self.update_status_file('Idle')
            self.shared_queue.clear_type('TRIGGER_RECORDING', 'AudioRecorder')
        except Exception as e:
            logger.error(f"Error handling PROCESSING_COMPLETE: {e} Line: {e.__traceback__.tb_lineno}")
            self.pending_row_data = None
            self.update_status_file('Idle')
        return True

class ProcessingThread(BaseThread):
    def __init__(self, shared_queue):
        super().__init__("ProcessingThread", shared_queue)
        self.executor = ThreadPoolExecutor(max_workers=1)

    def cleanup(self):
        """Cleanup resources for ProcessingThread."""
        self.executor.shutdown(wait=False)
        logger.info("ProcessingThread cleanup completed")

    def process_file(self, output_file, last_file_path, test_mode=None):
        def run_subprocess():
            try:
                start_message = {
                    "id": generate_message_id(),
                    "type": "PROCESSING_START",
                    "data": {},
                    "target": "AudioRecorder"
                }
                self.retry_on_failure(self.shared_queue.put, start_message)
                logger.info(f"Sent PROCESSING_START for file: {output_file}")

                logger.info(f"Processing file: {output_file}")
                template_file = test_mode.get('template_file', CONFIG['template_file']) if test_mode else CONFIG['template_file']
                parameters = [
                    "nice", "-n", "10", "ionice", "-c", "3", "python3", CONFIG['processing_module'],
                    "--find-offset-of", template_file,
                    "--within", output_file,
                ]
                logger.debug(f"Command to execute: {' '.join(parameters)}")
                p = subprocess.Popen(parameters, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                logger.info(f"Subprocess started with PID: {p.pid}")
                try:
                    output, errors = p.communicate(timeout=300)
                except subprocess.TimeoutExpired:
                    p.kill()
                    logger.error(f"Subprocess timed out after 300 seconds for {output_file}")
                    output, errors = "", "Subprocess timeout"
                except Exception as e:
                    logger.error(f"Subprocess error: {e} Line: {e.__traceback__.tb_lineno}")
                    output, errors = "", str(e)
                finally:
                    # Ensure PROCESSING_COMPLETE is sent even on failure
                    logger.debug(f"Raw subprocess output: {output!r}")
                    logger.debug(f"Subprocess stderr: {errors}")
                    logger.info(f"Subprocess completed with return code: {p.returncode}")
                    offset = "argument"
                    status = "error"
                    if p.returncode == 0:
                        import re
                        match = re.search(r"Clock accuracy:\s*([-+]?\d*\.?\d+)", output)
                        if match:
                            offset = match.group(1)
                            status = "success"
                            logger.info(f"Extracted offset: {offset}")
                        elif "No match" in output or "Error" in output:
                            logger.warning(f"Processing failed due to audio mismatch: {output!r}")
                            offset = "no_match"
                            status = "no_match"
                        else:
                            logger.error(f"Failed to parse offset from output: {output!r}")
                    else:
                        logger.error(f"Processing script failed with return code {p.returncode}. Stderr: {errors}")
                    message = {
                        "id": generate_message_id(),
                        "type": "PROCESSING_COMPLETE",
                        "data": {"offset": offset, "status": status},
                        "target": "AudioRecorder"
                    }
                    self.retry_on_failure(self.shared_queue.put, message)
                    logger.info(f"Sent PROCESSING_COMPLETE: {message}")
            except Exception as e:
                logger.error(f"Failed to start processing script: {e} Line: {e.__traceback__.tb_lineno}")
                message = {
                    "id": generate_message_id(),
                    "type": "PROCESSING_COMPLETE",
                    "data": {"offset": "argument", "status": "error"},
                    "target": "AudioRecorder"
                }
                self.retry_on_failure(self.shared_queue.put, message)
                logger.info(f"Sent PROCESSING_COMPLETE (error case): {message}")
        self.executor.submit(run_subprocess)

    def handle_queue_message(self, message):
        """Handle incoming messages for ProcessingThread."""
        logger.info(f"ProcessingThread received message, type: {message.get('type')}")
        if message["type"] == "STOP" and message.get("target", self.name) in [self.name, "ALL"]:
            logger.info(f"ProcessingThread shutting down")
            self.executor.shutdown(wait=False)
            return False
        elif message["type"] == "TRIGGER_PROCESSING" and message.get("target") == self.name:
            logger.info(f"Processing TRIGGER_PROCESSING for file: {message['data']['output_file']}")
            self.process_file(
                message['data']['output_file'],
                message['data']['last_file_path'],
                test_mode=message['data'].get('test_mode')
            )
            return True
        return True

def main():
    try:
        logger.info(f"Starting {os.path.basename(__file__)}")
        recordings_dir = os.path.dirname(CONFIG['last_file_path'])
        if not os.path.exists(recordings_dir):
            os.makedirs(recordings_dir)
            logger.info(f"Created recordings directory: {recordings_dir}")

        if os.path.exists(CONFIG['trigger_file']):
            with open(CONFIG['trigger_file'], 'w') as f:
                f.write('')
            logger.info(f"Cleared trigger file on startup: {CONFIG['trigger_file']}")

        shared_queue = PeekableQueue(maxsize=CONFIG['max_queue_size'])
        shared_queue.clear_type("TRIGGER_RECORDING", "AudioRecorder")
        logger.info(f"Cleared shared queue on startup, size: {shared_queue.qsize()}")

        threads = [
            GPS3ListenerThread(shared_queue),
            AudioRecorderThread(shared_queue),
            ProcessingThread(shared_queue),
        ]

        for thread in threads:
            thread.start()

        try:
            for thread in threads:
                thread.thread.join()
        except KeyboardInterrupt:
            logger.info("Received KeyboardInterrupt, stopping all threads")
            threads[1].update_status_file("Shutting Down")
            for thread in threads:
                thread.stop()
            for thread in threads:
                thread.thread.join()
            logger.info("All threads stopped")
            exit
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e} Line: {e.__traceback__.tb_lineno}")
            threads[1].update_status_file("Shutting Down")
            raise
            
    except Exception as e:
        logger.error(f"Error in main: {e} Line: {e.__traceback__.tb_lineno}")
        threads[1].update_status_file("Shutting Down")
        raise

if __name__ == "__main__":
    main()
