# pilfile10.py

from PIL import Image, ImageDraw, ImageFont
import logging
from time import strftime, localtime
import time
import spidev as SPI
import sys
import os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import colorlog
sys.path.append("..")
from lib import LCD_1inch28
import numpy
import csv

PI2 = numpy.pi * 2

# Raspberry Pi pin configuration
RST = 27
DC = 25
BL = 18
bus = 0
device = 0

# Configuration
CONFIG = {
    'recording_status_file': 'recording_status.txt',
    'latest_recording_file': 'latest_recording.txt',
    'log_file': os.path.join('logs', f"{os.path.splitext(os.path.basename(__file__))[0]}.log"),
    'font1_path': 'Font/Font01.ttf',
    'font2_path': 'Font/Font02.ttf',
    'status_colors': {
        'Initial': {
            'background': (128, 128, 128),  # Grey
            'text': (0, 0, 0)  # Black text
        },
        'Idle': {
            'background': (20, 20, 20),  # Black
            'text': (255, 255, 255)  # White text
        },
        'Recording': {
            'background': (0, 150, 0),  # Green
            'text': (0, 0, 0)  # Black text
        },
        'Cooldown': {
            'background': (170, 0, 170),  # Purple
            'text': (255, 255, 255)  # White text
        },
        'Processing': {
            'background': (255, 165, 0),  # Orange
            'text': (0, 0, 0)  # Black text
        },
        'ProcessSuccess': {
            'background': (0, 0, 255),  # Blue
            'text': (255, 255, 255)  # White text
        },
        'ProcessFailure': {
            'background': (255, 69, 0),  # Red-Orange
            'text': (255, 255, 255)  # White text
        },
        'Shutting Down': {
            'background': (255, 0, 0),  # Red
            'text': (255, 255, 255)  # White text
        }
    }
}

def setup_logging(log_file):
    try:
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
            logging.info(f"Created log directory: {log_dir}")

        console_handler = colorlog.StreamHandler()
        console_handler.setFormatter(colorlog.ColoredFormatter(
            '%(log_color)s%(levelname)s:%(name)s:%(message)s',
            log_colors={
                'DEBUG': 'cyan',
                'INFO': 'green',
                'WARNING': 'yellow',
                'ERROR': 'red',
                'CRITICAL': 'red,bg_white',
            }
        ))

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(threadName)s: %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                console_handler
            ]
        )
        logger = logging.getLogger(__name__)
        logger.info(f"Logging initialized, writing to {log_file}")
        return logger
    except Exception as e:
        print(f"Failed to initialize logging: {e}")
        raise

logger = setup_logging(CONFIG['log_file'])

# Check for font files
def check_fonts():
    font_files = [CONFIG['font1_path'], CONFIG['font2_path']]
    missing_fonts = [f for f in font_files if not os.path.exists(f)]
    if missing_fonts:
        logger.error(f"Missing font files: {', '.join(missing_fonts)}")
        try:
            # Attempt to use a default system font
            default_font = ImageFont.load_default()
            logger.warning("Falling back to default PIL font")
            return default_font, default_font
        except Exception as e:
            logger.critical(f"Cannot load default font: {e}. Exiting.")
            sys.exit(1)
    return None, None

# Initialize fonts
Font1_default, Font2_default = check_fonts()
Font1 = Font1_default or ImageFont.truetype(CONFIG['font1_path'], 25)
Font2 = Font1_default or ImageFont.truetype(CONFIG['font1_path'], 18)
Font3 = Font2_default or ImageFont.truetype(CONFIG['font2_path'], 40)
Font4 = Font1_default or ImageFont.truetype(CONFIG['font1_path'], 20)

# Initialize LCD display
try:
    disp = LCD_1inch28.LCD_1inch28()
    disp.Init()
    disp.clear()
    disp.bl_DutyCycle(50)
except IOError as e:
    logger.error(f"IOError initializing LCD: {e}")
    sys.exit(1)

# Global variables
current_image = None
last_data = None
last_status = None
last_update_time = 0
update_interval = 1.0

def read_recording_status(file_path):
    try:
        with open(file_path, 'r', newline='') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if not rows:
                logger.warning(f"Empty CSV file: {file_path}")
                return {"Status": "Idle", "Lat": "0.0", "Lon": "0.0", "Temp1": "None", "Temp2": "None", "Temp3": "None", "Temp4": "None", "Temp5": "None", "Offset": ""}
            return rows[-1]
    except FileNotFoundError:
        logger.error(f"File {file_path} not found, returning default")
        return {"Status": "Idle", "Lat": "0.0", "Lon": "0.0", "Temp1": "None", "Temp2": "None", "Temp3": "None", "Temp4": "None", "Temp5": "None", "Offset": ""}
    except Exception as e:
        logger.error(f"Error reading recording status from {file_path}: {e}")
        return {"Status": "Idle", "Lat": "0.0", "Lon": "0.0", "Temp1": "None", "Temp2": "None", "Temp3": "None", "Temp4": "None", "Temp5": "None", "Offset": ""}

def clock(data=None, status="Idle"):
    color_config = CONFIG['status_colors'].get(status, CONFIG['status_colors']['Idle'])
    background_color = color_config['background']
    text_color = color_config['text']

    im = Image.new('RGB', (240, 240), color=background_color)
    draw = ImageDraw.Draw(im)

    #draw.line((0, 0) + im.size, fill=128)
    #draw.line((0, im.size[1], im.size[0], 0), fill=128)
    draw.arc((1, 1, 239, 239), 0, 360, fill=(0, 0, 255))
    draw.arc((2, 2, 238, 238), 0, 360, fill=(0, 0, 255))
    draw.arc((3, 3, 237, 237), 0, 360, fill=(0, 0, 255))
    draw.line([(120, 1), (120, 12)], fill=(128, 255, 128), width=4)
    draw.line([(120, 227), (120, 239)], fill=(128, 255, 128), width=4)
    draw.line([(1, 120), (12, 120)], fill=(128, 255, 128), width=4)
    draw.line([(227, 120), (239, 120)], fill=(128, 255, 128), width=4)

    draw.text(
        (120 - draw.textlength('Sandbells', Font2) / 2, 20),
        'Sandbells',
        fill=(128, 255, 128),
        font=Font2
    )

    def calculate_hand(centre, length, value, sections):
        y = -length * numpy.cos(PI2 * (value / sections)) + centre[0]
        x = length * numpy.sin(PI2 * (value / sections)) + centre[1]
        return x, y

    sec_value = float(strftime("%S", localtime()))
    min_value = float(strftime("%M", localtime()))
    hrs_value = float(strftime("%H", localtime()))
    sec_values = calculate_hand((120, 120), 100, sec_value, 60)
    min_values = calculate_hand((120, 120), 80, min_value, 60)
    hrs_values = calculate_hand((120, 120), 60, hrs_value + min_value / 60, 12)

    draw.line([(120, 120), hrs_values], fill="YELLOW", width=5)
    draw.line([(120, 120), min_values], fill="BLUE", width=4)
    draw.line([(120, 120), sec_values], fill="RED", width=3)

    if data:
        y_offset = 150
        temps = [data.get(f'Temp{i+1}', 'None') for i in range(5)]
        valid_temps = [t for t in temps if t != 'None']
        if valid_temps:
            temp_text = f"Temps: {', '.join(valid_temps)}°C"
            draw.text(
                (120 - draw.textlength(temp_text, Font4) / 2, y_offset),
                temp_text,
                fill=text_color,
                font=Font4
            )
            y_offset += 20
        if 'Lat' in data and data['Lat'] != 'Lat: 00.0000000':
            draw.text(
                (120 - draw.textlength(f"Lat: {data['Lat']}", Font4) / 2, y_offset),
                f"Lat: {data['Lat']}",
                fill=text_color,
                font=Font4
            )
            y_offset += 20
        if 'Lon' in data and data['Lon'] != 'Lon: 00.0000000':
            draw.text(
                (120 - draw.textlength(f"Lon: {data['Lon']}", Font4) / 2, y_offset),
                f"Lon: {data['Lon']}",
                fill=text_color,
                font=Font4
            )
            y_offset += 20
        if 'Offset' in data and data['Offset']:
            draw.text(
                (120 - draw.textlength(f"Offset: {data['Offset']}", Font4) / 2, y_offset),
                f"Offset: {data['Offset']}",
                fill=text_color,
                font=Font4
            )

    text = strftime("%H:%M:%S", localtime())
    draw.text(
        (120 - draw.textlength(text, Font3) / 2, 50),
        text,
        fill=text_color,
        font=Font3
    )

    # im = im.rotate(180)
    return im

class FileChangeHandler(FileSystemEventHandler):
    def __init__(self, target_files):
        self.target_files = target_files

    def on_modified(self, event):
        if not event.is_directory and event.src_path in self.target_files:
            logger.debug(f"File {event.src_path} modified, updating display with {event}")
            global last_data, last_status
            if event.src_path.endswith('recording_status.txt'):
                last_data = read_recording_status(event.src_path)
                new_status = last_data.get('Status', 'Idle')
                if new_status != last_status:
                    logger.info(f"Status changed to '{new_status}' with data: {last_data}")
                last_status = new_status
                update_display()

def update_display():
    global current_image, last_update_time, last_data, last_status
    current_time = int(time.time())

    new_data = read_recording_status(CONFIG['recording_status_file'])
    new_status = new_data.get('Status', 'Idle')

    data_changed = last_data != new_data
    status_changed = new_status != last_status
    time_elapsed = current_time >= last_update_time + update_interval

    if time_elapsed or status_changed or data_changed:
        if status_changed:
            logger.info(f"Status changed to '{new_status}' with data: {new_data}")
        elif data_changed:
            logger.info(f"Data changed: {new_data}")
        last_update_time = current_time
        last_status = new_status
        last_data = new_data
        current_image = clock(last_data, last_status)
        try:
            # Ensure the RAM disk directory exists
            ramdisk_path = '/tmp/ramdisk'
            if not os.path.exists(ramdisk_path):
                os.makedirs(ramdisk_path)
                logger.info(f"Created RAM disk directory: {ramdisk_path}")

            # Capture pre-save time
            pre_save_time = time.time()
            
            # Save the image to the RAM disk
            image_path = os.path.join(ramdisk_path, 'clock_face.png')
            current_image.save(image_path)
            logger.debug(f"Saved clock image to {image_path}")
            
            # Capture post-save time and calculate difference in milliseconds
            post_save_time = time.time()
            time_diff_ms = (post_save_time - pre_save_time) * 1000
            logger.debug(f"Time difference for saving clock_face.png: {time_diff_ms:.2f} ms")   # 37mS
            
            current_image = current_image.rotate(180)
            
            disp.ShowImage(current_image)
            if status_changed or data_changed:
                logger.info(f"Display updated to {new_status}")
        except Exception as e:
            logger.error(f"Error processing image: {e}")

def main():
    default_files = [
        os.path.join(os.path.dirname(__file__), CONFIG['recording_status_file'])
    ]
    files_to_watch = sys.argv[1:] if len(sys.argv) > 1 else default_files

    for file_to_watch in files_to_watch:
        if not os.path.exists(file_to_watch):
            logger.error(f"File {file_to_watch} does not exist.")
            try:
                with open(file_to_watch, 'w', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=['Status', 'Lat', 'Lon', 'Temp1', 'Temp2', 'Temp3', 'Temp4', 'Temp5', 'Offset'], quoting=csv.QUOTE_MINIMAL)
                    writer.writeheader()
                    writer.writerow({
                        'Status': 'Idle',
                        'Lat': '0.0',
                        'Lon': '0.0',
                        'Temp1': 'None',
                        'Temp2': 'None',
                        'Temp3': 'None',
                        'Temp4': 'None',
                        'Temp5': 'None',
                        'Offset': ''
                    })
                logger.info(f"Created {file_to_watch}")
            except Exception as e:
                logger.error(f"Error creating {file_to_watch}: {e}")
                sys.exit(1)

    logger.info(f"Monitoring files: {files_to_watch}")

    global last_data, last_status, current_image
    last_status = 'Initial'
    last_data = {"Status": "Initial", "Lat": "0.0", "Lon": "0.0", "Temp1": "None", "Temp2": "None", "Temp3": "None", "Temp4": "None", "Temp5": "None", "Offset": ""}
    current_image = clock(last_data, last_status)
    try:
        disp.ShowImage(current_image)
        logger.info("Initial display updated to Initial")
    except Exception as e:
        logger.error(f"Error displaying initial image: {e}")

    last_data = read_recording_status(default_files[0])
    last_status = last_data.get('Status', 'Idle')
    current_image = clock(last_data, last_status)
    try:
        disp.ShowImage(current_image)
        logger.info(f"Display updated to {last_status}")
    except Exception as e:
        logger.error(f"Error displaying initial status image: {e}")

    event_handler = FileChangeHandler(files_to_watch)
    observer = Observer()
    for file_to_watch in files_to_watch:
        observer.schedule(event_handler, path=file_to_watch, recursive=False)
    observer.start()

    try:
        while True:
            update_display()
            time.sleep(update_interval)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        last_status = 'Shutting Down'
        current_image = clock(last_data, last_status)
        try:
            disp.ShowImage(current_image)
            logger.info("Display updated to Shutting Down")
            time.sleep(1)
        except Exception as e:
            logger.error(f"Error displaying shutting down image: {e}")
        observer.stop()
        disp.module_exit()
        logger.info("Quit")
        sys.exit(0)
    except Exception as e:
        logger.info("Shutting down due to error...")
        last_status = 'Shutting Down'
        current_image = clock(last_data, last_status)
        try:
            disp.ShowImage(current_image)
            logger.info("Display updated to Shutting Down")
            time.sleep(1)
        except Exception as e:
            logger.error(f"Error displaying shutting down image: {e}")
        logger.error(f"Error: {e}")
        observer.stop()
        disp.module_exit()
        sys.exit(1)
    observer.join()

if __name__ == "__main__":
    main()
