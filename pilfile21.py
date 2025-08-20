# pilfile21.py

from PIL import Image, ImageDraw, ImageFont
import logging
import math
import random
import csv
from datetime import datetime, timedelta
import os
from time import strftime, localtime, mktime
import time
import spidev as SPI
import sys
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import colorlog
import numpy
sys.path.append("..")
from lib import LCD_1inch28

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
    'use_test_data': True,
    'display_mode': 'text',  # Default to text mode
    'default_background_color': (230, 230, 230),  # Very light grey
    'clock_text_color': (0, 0, 0),  # Black for HH:MM:SS and lat/lon/temps
    'status_colors': {
        'Initial': {'background': (170, 170, 170), 'text': (0, 0, 0)},
        'Idle': {'background': (20, 20, 20), 'text': (255, 255, 255)},
        'Recording': {'background': (0, 150, 0), 'text': (0, 0, 0)},
        'Cooldown': {'background': (170, 0, 170), 'text': (255, 255, 255)},
        'Processing': {'background': (255, 165, 0), 'text': (0, 0, 0)},
        'ProcessSuccess': {'background': (0, 0, 255), 'text': (255, 255, 255)},
        'ProcessFailure': {'background': (255, 69, 0), 'text': (255, 255, 255)},
        'Shutting Down': {'background': (255, 0, 0), 'text': (255, 255, 255)}
    },
    'clock_center': (120, 120),
    'clock_radius': 112,
    'clock_angle': 0
}

# Ramdisk paths
background_ramdisk_path = "/tmp/Ramdisk/ring_test.png"
clock_ramdisk_path = "/tmp/Ramdisk/clock_face.png"

# Global variables
current_image = None
last_data = None
last_status = None
last_update_time = 0
update_interval = 1.0
last_background_update = None

def setup_logging(log_file):
    """Initialize logging with file and console output."""
    try:
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
            logging.info(f"Created log directory: {log_dir}")
        console_handler = colorlog.StreamHandler()
        console_handler.setFormatter(colorlog.ColoredFormatter(
            '%(log_color)s%(levelname)s:%(name)s:%(message)s',
            log_colors={
                'DEBUG': 'cyan', 'INFO': 'green', 'WARNING': 'yellow',
                'ERROR': 'red', 'CRITICAL': 'red,bg_white'
            }
        ))
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(threadName)s: %(levelname)s - %(message)s',
            handlers=[logging.FileHandler(log_file), console_handler]
        )
        logger = logging.getLogger(__name__)
        logger.info(f"Logging initialized, writing to {log_file}")
        return logger
    except Exception as e:
        print(f"Failed to initialize logging: {e}")
        raise

logger = setup_logging(CONFIG['log_file'])

def check_fonts():
    """Check for font files and fall back to default if missing."""
    font_files = [CONFIG['font1_path'], CONFIG['font2_path']]
    missing_fonts = [f for f in font_files if not os.path.exists(f)]
    if missing_fonts:
        logger.error(f"Missing font files: {', '.join(missing_fonts)}")
        try:
            default_font = ImageFont.load_default()
            logger.warning("Falling back to default PIL font")
            return default_font, default_font
        except Exception as e:
            logger.critical(f"Cannot load default font: {e}. Exiting.")
            sys.exit(1)
    return None, None

Font1_default, Font2_default = check_fonts()
Font1 = Font1_default or ImageFont.truetype(CONFIG['font1_path'], 25)
Font2 = Font1_default or ImageFont.truetype(CONFIG['font1_path'], 18)
Font3 = Font2_default or ImageFont.truetype(CONFIG['font2_path'], 40)
Font4 = Font1_default or ImageFont.truetype(CONFIG['font1_path'], 20)

def initialize_display():
    """Initialize the LCD display."""
    try:
        disp = LCD_1inch28.LCD_1inch28()
        disp.Init()
        disp.clear()
        disp.bl_DutyCycle(50)
        return disp
    except IOError as e:
        logger.error(f"IOError initializing LCD: {e}")
        sys.exit(1)

disp = initialize_display()

def generate_test_data():
    """Generate test data for 8 days, 20 points each."""
    data = []
    for day in range(8):
        for i in range(20):
            t = i * 1.2
            if random.random() < 0.05:
                offset = random.uniform(-240, -60) if random.random() < 0.5 else random.uniform(60, 240)
            else:
                offset = random.uniform(-60, 60)
            offset += 10
            offset = min(max(offset, -240), 240)
            data.append([offset, t])
    logger.info("Generated test data for background")
    return data

def read_csv_data(csv_file, today):
    """Read data from CSV for the past 7 days."""
    existing_data = []
    try:
        with open(csv_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    row_date = datetime.strptime(row["date"], "%Y-%m-%d").date()
                    if today - timedelta(days=7) <= row_date <= today - timedelta(days=1):
                        existing_data.append([float(row["accuracy_seconds"]), float(row["time_hours"]), row_date])
                except (ValueError, KeyError) as e:
                    logger.warning(f"Invalid row in {csv_file}: {e}")
        logger.info(f"Read {len(existing_data)} points from {csv_file}")
    except FileNotFoundError:
        logger.warning(f"{csv_file} not found")
    return existing_data

def generate_today_data():
    """Generate random data for today."""
    today_data = []
    today = datetime.now().date()
    for i in range(20):
        t = i * 1.2
        if random.random() < 0.05:
            offset = random.uniform(-240, -60) if random.random() < 0.5 else random.uniform(60, 240)
        else:
            offset = random.uniform(-60, 60)
        offset += 10
        offset = min(max(offset, -240), 240)
        today_data.append([offset, t, today])
    return today_data

def pad_data(data, today):
    """Pad data to ensure 160 points (8 days, 20 points each)."""
    if len(data) < 160:
        logger.warning(f"Only {len(data)} points, padding with random data")
        for day_offset in range(1, 8):
            day = today - timedelta(days=day_offset)
            day_points = [d for d in data if d[2] == day]
            if len(day_points) < 20:
                for i in range(20 - len(day_points)):
                    t = i * 1.2
                    offset = random.uniform(-60, 60) + 10
                    offset = min(max(offset, -240), 240)
                    data.append([offset, t, day])
    return sorted(data, key=lambda x: x[2], reverse=True)[:160]

def save_csv_data(csv_file, today_data, existing_data, today):
    """Save data to CSV, keeping only the last 7 days."""
    with open(csv_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "accuracy_seconds", "time_hours"])
        writer.writeheader()
        for offset, t, date in today_data + existing_data:
            if today - timedelta(days=7) <= date <= today:
                writer.writerow({"date": date.strftime("%Y-%m-%d"), "accuracy_seconds": offset - 10, "time_hours": t})

def load_or_generate_data(csv_file="accuracy.csv"):
    """Load or generate 160 data points for background."""
    today = datetime.now().date()
    if CONFIG['use_test_data']:
        data = generate_test_data()
    else:
        existing_data = read_csv_data(csv_file, today)
        today_data = generate_today_data()
        data = today_data + existing_data
        data = pad_data(data, today)
        save_csv_data(csv_file, today_data, existing_data, today)
        data = [[offset, t] for offset, t, _ in data]
    
    if len(data) != 160:
        logger.error(f"Expected 160 points, got {len(data)}")
        raise ValueError("Insufficient data points")
    return data

def create_background_image(bg_color, width=240, height=240):
    """Create a new background image with the specified color."""
    return Image.new("RGB", (width, height), bg_color)

def draw_data_points(image, data):
    """Draw data points as colored dots on concentric rings."""
    width, height = image.size
    center = (width // 2, height // 2)
    outer_radius = 119
    colors = [(255, 255, 255), (255, 0, 0), (255, 165, 0), (255, 255, 0), 
              (0, 255, 0), (0, 255, 255), (0, 0, 255), (128, 0, 128)]
    draw = ImageDraw.Draw(image)
    
    for day in range(8):
        radius = outer_radius - day
        for i in range(20):
            idx = day * 20 + i
            offset, hour = data[idx]
            angle_deg = -90 + (offset / 60) * 45
            angle_rad = math.radians(angle_deg)
            luminance = 255 - 63.5 * abs(math.sin(math.pi * hour / 12))
            color = colors[day]
            scaled_color = tuple(int(c * luminance / 255) for c in color)
            x = center[0] + radius * math.cos(angle_rad)
            y = center[1] + radius * math.sin(angle_rad)
            draw.ellipse([x - 0.5, y - 0.5, x + 0.5, y + 0.5], fill=scaled_color)

def save_background_image(image, path):
    """Save the background image to the specified ramdisk path."""
    ramdisk_dir = os.path.dirname(path)
    if not os.path.exists(ramdisk_dir):
        os.makedirs(ramdisk_dir)
        logger.info(f"Created ramdisk directory: {ramdisk_dir}")
    image.save(path)
    logger.info(f"Saved background image to {path}")

def generate_background(status="Initial"):
    """Generate the background image with data points."""
    bg_color = CONFIG['default_background_color'] if CONFIG['display_mode'] == 'text' else \
               CONFIG['status_colors'].get(status, CONFIG['status_colors']['Idle'])['background']
    logger.debug(f"Generating background with color {bg_color} for status {status} in {CONFIG['display_mode']} mode")
    
    image = create_background_image(bg_color)
    data = load_or_generate_data()
    draw_data_points(image, data)
    save_background_image(image, background_ramdisk_path)
    return image

def load_background_image(status):
    """Load the background image or generate a new one if not found."""
    try:
        return Image.open(background_ramdisk_path).convert("RGB")
    except FileNotFoundError:
        logger.warning(f"Background {background_ramdisk_path} not found, generating new with status {status}")
        return generate_background(status)

def draw_clock_arcs(draw, center, radius):
    """Draw the blue arcs of the clock face."""
    draw.arc((center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius), 
             0, 360, fill=(0, 0, 255))
    draw.arc((center[0] - radius + 1, center[1] - radius + 1, center[0] + radius - 1, center[1] + radius - 1), 
             0, 360, fill=(0, 0, 255))
    draw.arc((center[0] - radius + 2, center[1] - radius + 2, center[0] + radius - 2, center[1] + radius - 2), 
             0, 360, fill=(0, 0, 255))

def draw_clock_radial_lines(draw, center, radius):
    """Draw the green radial lines of the clock face."""
    draw.line([(center[0], center[1] - radius), (center[0], center[1] - radius + 11)], 
              fill=(128, 255, 128), width=4)
    draw.line([(center[0], center[1] + radius), (center[0], center[1] + radius - 11)], 
              fill=(128, 255, 128), width=4)
    draw.line([(center[0] - radius, center[1]), (center[0] - radius + 11, center[1])], 
              fill=(128, 255, 128), width=4)
    draw.line([(center[0] + radius, center[1]), (center[0] + radius - 11, center[1])], 
              fill=(128, 255, 128), width=4)

def draw_clock_face(draw, center, radius):
    """Draw the complete clock face (arcs and radial lines)."""
    draw_clock_arcs(draw, center, radius)
    draw_clock_radial_lines(draw, center, radius)

def calculate_hand_endpoint(center, length, value, sections):
    """Calculate the endpoint of a clock hand."""
    y = -length * numpy.cos(PI2 * (value / sections)) + center[0]
    x = length * numpy.sin(PI2 * (value / sections)) + center[1]
    return x, y

def draw_main_hands(draw, center, hrs_values, min_values, sec_values):
    """Draw the main clock hands in mid-grey."""
    draw.line([(center[0], center[1]), hrs_values], fill=(128, 128, 128), width=5)
    draw.line([(center[0], center[1]), min_values], fill=(128, 128, 128), width=4)
    draw.line([(center[0], center[1]), sec_values], fill=(128, 128, 128), width=3)

def draw_small_hands(draw, sec_values, min_values, hrs_values, sec_angle, min_angle, hrs_angle):
    """Draw small red hands at the ends of main hands."""
    small_hand_length = 5
    small_hand_width = 2
    sec_small_end = (
        sec_values[0] + small_hand_length * math.sin(sec_angle),
        sec_values[1] - small_hand_length * math.cos(sec_angle)
    )
    min_small_end = (
        min_values[0] + small_hand_length * math.sin(min_angle),
        min_values[1] - small_hand_length * math.cos(min_angle)
    )
    hrs_small_end = (
        hrs_values[0] + small_hand_length * math.sin(hrs_angle),
        hrs_values[1] - small_hand_length * math.cos(hrs_angle)
    )
    draw.line([sec_values, sec_small_end], fill=(255, 0, 0), width=small_hand_width)
    draw.line([min_values, min_small_end], fill=(255, 0, 0), width=small_hand_width)
    draw.line([hrs_values, hrs_small_end], fill=(255, 0, 0), width=small_hand_width)

def draw_clock_hands(draw, center, radius, time_struct):
    """Draw the clock hands with small red hands at their ends."""
    sec_value = float(time_struct.tm_sec)
    min_value = float(time_struct.tm_min)
    hrs_value = float(time_struct.tm_hour)
    sec_length = int(0.63 * radius)
    min_length = int(0.45 * radius)
    hrs_length = int(0.27 * radius)

    # Calculate main hand endpoints
    sec_values = calculate_hand_endpoint(center, sec_length, sec_value, 60)
    min_values = calculate_hand_endpoint(center, min_length, min_value, 60)
    hrs_values = calculate_hand_endpoint(center, hrs_length, hrs_value + min_value / 60, 12)

    # Calculate angles for small hands
    sec_angle = PI2 * (sec_value / 60)
    min_angle = PI2 * (min_value / 60)
    hrs_angle = PI2 * ((hrs_value + min_value / 60) / 12)

    # Draw main and small hands
    draw_main_hands(draw, center, hrs_values, min_values, sec_values)
    draw_small_hands(draw, sec_values, min_values, hrs_values, sec_angle, min_angle, hrs_angle)

def draw_centered_text(draw, text, y_pos, font, fill_color):
    """Draw centered text at the specified y position."""
    x_pos = 120 - draw.textlength(text, font) / 2
    draw.text((x_pos, y_pos), text, fill=fill_color, font=font)

def draw_time_text(draw, time_struct):
    """Draw the time text in HH:MM:SS format."""
    text = strftime("%H:%M:%S", time_struct)
    draw_centered_text(draw, text, 50, Font3, CONFIG['clock_text_color'])

def draw_status_box(draw, status, text_color):
    """Draw the status text in a colored box for non-Idle statuses in text mode."""
    text_width = draw.textlength(status, Font4)
    text_height = 20  # Approximate height for Font4
    box_padding = 5
    box_x0 = 120 - (text_width / 2) - box_padding
    box_y0 = 150 - (text_height / 2) - box_padding
    box_x1 = 120 + (text_width / 2) + box_padding
    box_y1 = 150 + (text_height / 2) + box_padding
    color_config = CONFIG['status_colors'].get(status, CONFIG['status_colors']['Idle'])
    draw.rectangle([box_x0, box_y0, box_x1, box_y1], fill=color_config['background'])
    draw_centered_text(draw, status, 150 - text_height / 2, Font4, text_color)
    logger.debug(f"Drew status box for {status} with background {color_config['background']}")

def draw_status_info(draw, data, status, text_color):
    """Draw status-dependent text: status box or lat/lon/temps."""
    if CONFIG['display_mode'] == 'text' and status != 'Idle':
        draw_status_box(draw, status, text_color)
    else:
        y_offset = 150
        if data:
            temps = [data.get(f'Temp{i+1}', 'None') for i in range(5)]
            valid_temps = [t for t in temps if t != 'None']
            if valid_temps:
                temp_text = f"Temps: {', '.join(valid_temps)}°C"
                draw_centered_text(draw, temp_text, y_offset, Font4, CONFIG['clock_text_color'])
                y_offset += 20
            if 'Lat' in data and data['Lat'] != 'Lat: 00.0000000':
                draw_centered_text(draw, f"Lat: {data['Lat']}", y_offset, Font4, CONFIG['clock_text_color'])
                y_offset += 20
            if 'Lon' in data and data['Lon'] != 'Lon: 00.0000000':
                draw_centered_text(draw, f"Lon: {data['Lon']}", y_offset, Font4, CONFIG['clock_text_color'])
                y_offset += 20
            if 'Offset' in data and data['Offset']:
                draw_centered_text(draw, f"Offset: {data['Offset']}", y_offset, Font4, CONFIG['clock_text_color'])
        logger.debug(f"Drew lat/lon/temps for status {status} in {CONFIG['display_mode']} mode")

def create_transparent_image(bg_size):
    """Create a transparent RGBA image."""
    return Image.new('RGBA', bg_size, (0, 0, 0, 0))

def composite_images(bg_image, overlay_image):
    """Composite background and overlay images."""
    return Image.alpha_composite(bg_image.convert("RGBA"), overlay_image).convert("RGB")

def save_clock_image(image, path):
    """Save the clock image to the specified ramdisk path."""
    try:
        pre_save_time = time.time()
        image.save(path)
        post_save_time = time.time()
        logger.debug(f"Saved clock image to {path}, took {(post_save_time - pre_save_time) * 1000:.2f} ms")
    except Exception as e:
        logger.error(f"Error saving clock image to {path}: {e}")

def draw_clock_elements(draw, center, radius, time_struct, data, status, text_color):
    """Draw all clock elements on the image, with hands last."""
    draw_clock_face(draw, center, radius)
    draw_centered_text(draw, 'Sandbells', 20, Font2, (255, 0, 0))
    draw_time_text(draw, time_struct)
    draw_status_info(draw, data, status, text_color)
    draw_clock_hands(draw, center, radius, time_struct)  # Draw hands last to obscure text

def clock(data=None, status="Idle"):
    """Generate the clock image, saving PNG one second ahead."""
    color_config = CONFIG['status_colors'].get(status, CONFIG['status_colors']['Idle'])
    text_color = color_config['text']
    center = CONFIG['clock_center']
    radius = CONFIG['clock_radius']
    current_time = localtime()
    advanced_time = localtime(mktime(current_time) + 1)

    # Load background (very light grey in text mode)
    bg_image = load_background_image(status)

    # LCD image (current time)
    lcd_image = create_transparent_image(bg_image.size)
    lcd_draw = ImageDraw.Draw(lcd_image)
    draw_clock_elements(lcd_draw, center, radius, current_time, data, status, text_color)
    lcd_image = composite_images(bg_image, lcd_image)

    # PNG image (advanced time)
    png_image = create_transparent_image(bg_image.size)
    png_draw = ImageDraw.Draw(png_image)
    draw_clock_elements(png_draw, center, radius, advanced_time, data, status, text_color)
    png_image = composite_images(bg_image, png_image)
    save_clock_image(png_image, clock_ramdisk_path)

    return lcd_image

def read_recording_status(file_path):
    """Read the latest recording status from a CSV file."""
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
        logger.error(f"Error reading recording status: {e}")
        return {"Status": "Idle", "Lat": "0.0", "Lon": "0.0", "Temp1": "None", "Temp2": "None", "Temp3": "None", "Temp4": "None", "Temp5": "None", "Offset": ""}

def check_background_update_needed(today):
    """Check if the background needs updating based on the date."""
    return last_background_update != today

def read_new_status_data():
    """Read the latest status data from the recording status file."""
    return read_recording_status(CONFIG['recording_status_file'])

def check_update_conditions(current_time, new_data, new_status):
    """Check if an update is needed based on time, data, or status changes."""
    data_changed = last_data != new_data
    status_changed = new_status != last_status
    time_elapsed = current_time >= last_update_time + update_interval
    return time_elapsed or status_changed or data_changed, data_changed, status_changed

def update_globals(current_time, new_data, new_status):
    """Update global variables with new data and status."""
    global last_update_time, last_data, last_status
    last_update_time = current_time
    last_data = new_data
    last_status = new_status

def display_image(image):
    """Display the image on the LCD with rotation."""
    try:
        rotated_image = image.rotate(180)
        disp.ShowImage(rotated_image)
        logger.info(f"Display updated to {last_status}")
    except Exception as e:
        logger.error(f"Error displaying image: {e}")

def update_display():
    """Update the LCD display with the current image."""
    global last_background_update
    try:
        current_time = int(time.time())
        today = datetime.now().date()

        # Check if background needs updating
        if check_background_update_needed(today):
            logger.info("New day, generating background")
            generate_background(last_status)
            last_background_update = today

        # Read new status data
        new_data = read_new_status_data()
        new_status = new_data.get('Status', 'Idle')

        # Check update conditions
        should_update, data_changed, status_changed = check_update_conditions(current_time, new_data, new_status)

        if should_update:
            if status_changed:
                logger.info(f"Status changed to '{new_status}'")
            elif data_changed:
                logger.info(f"Data changed: {new_data}")
            update_globals(current_time, new_data, new_status)
            global current_image
            current_image = clock(last_data, last_status)
            display_image(current_image)
    except Exception as e:
        logger.error(f"Error in update_display: {e}")

def initialize_files(files_to_watch):
    """Initialize watched files if they don't exist."""
    for file_to_watch in files_to_watch:
        if not os.path.exists(file_to_watch):
            logger.error(f"File {file_to_watch} does not exist")
            try:
                with open(file_to_watch, 'w', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=['Status', 'Lat', 'Lon', 'Temp1', 'Temp2', 'Temp3', 'Temp4', 'Temp5', 'Offset'])
                    writer.writeheader()
                    writer.writerow({
                        'Status': 'Idle', 'Lat': '0.0', 'Lon': '0.0',
                        'Temp1': 'None', 'Temp2': 'None', 'Temp3': 'None',
                        'Temp4': 'None', 'Temp5': 'None', 'Offset': ''
                    })
                logger.info(f"Created {file_to_watch}")
            except Exception as e:
                logger.error(f"Error creating {file_to_watch}: {e}")
                sys.exit(1)

def initialize_display_state():
    """Initialize global state and display the initial image."""
    global last_data, last_status, current_image, last_background_update
    last_status = 'Initial'
    last_data = {"Status": "Initial", "Lat": "0.0", "Lon": "0.0", "Temp1": "None", "Temp2": "None", "Temp3": "None", "Temp4": "None", "Temp5": "None", "Offset": ""}
    last_background_update = datetime.now().date()
    try:
        generate_background(last_status)
        current_image = clock(last_data, last_status)
        ramdisk_dir = os.path.dirname(clock_ramdisk_path)
        if not os.path.exists(ramdisk_dir):
            os.makedirs(ramdisk_dir)
            logger.info(f"Created ramdisk directory: {ramdisk_dir}")
        display_image(current_image)
        logger.info("Initial display updated")
    except Exception as e:
        logger.error(f"Error displaying initial image: {e}")
        sys.exit(1)

def update_initial_status(default_files):
    """Update the display with the initial status from the status file."""
    global last_data, last_status, current_image
    last_data = read_recording_status(default_files[0])
    last_status = last_data.get('Status', 'Idle')
    try:
        current_image = clock(last_data, last_status)
        display_image(current_image)
        logger.info(f"Display updated to {last_status}")
    except Exception as e:
        logger.error(f"Error displaying initial status image: {e}")
        sys.exit(1)

def setup_file_observer(files_to_watch):
    """Set up the file observer for monitoring status changes."""
    event_handler = FileChangeHandler(files_to_watch)
    observer = Observer()
    for file_to_watch in files_to_watch:
        observer.schedule(event_handler, path=file_to_watch, recursive=False)
    observer.start()
    return observer

def handle_shutdown():
    """Handle program shutdown with a final display update."""
    global last_status, current_image
    logger.info("Shutting down...")
    last_status = 'Shutting Down'
    try:
        current_image = clock(last_data, last_status)
        display_image(current_image)
        logger.info("Display updated to Shutting Down")
        time.sleep(1)
    except Exception as e:
        logger.error(f"Error displaying shutting down image: {e}")
    disp.module_exit()
    logger.info("Quit")

def main():
    """Main program loop to initialize and monitor display updates."""
    default_files = [os.path.join(os.path.dirname(__file__), CONFIG['recording_status_file'])]
    files_to_watch = sys.argv[1:] if len(sys.argv) > 1 else default_files

    initialize_files(files_to_watch)
    logger.info(f"Monitoring files: {files_to_watch}")

    initialize_display_state()
    update_initial_status(default_files)
    observer = setup_file_observer(files_to_watch)

    try:
        while True:
            update_display()
            time.sleep(update_interval)
    except KeyboardInterrupt:
        handle_shutdown()
        observer.stop()
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unexpected error in main loop: {e}")
        handle_shutdown()
        observer.stop()
        sys.exit(1)

class FileChangeHandler(FileSystemEventHandler):
    """Handle file modifications for watched files."""
    def __init__(self, target_files):
        self.target_files = target_files

    def on_modified(self, event):
        if not event.is_directory and event.src_path in self.target_files:
            logger.debug(f"File {event.src_path} modified")
            global last_data, last_status
            if event.src_path.endswith('recording_status.txt'):
                last_data = read_recording_status(event.src_path)
                new_status = last_data.get('Status', 'Idle')
                if new_status != last_status:
                    logger.info(f"Status changed to '{new_status}', regenerating background")
                    generate_background(new_status)
                if new_status != last_status:
                    logger.info(f"Status changed to '{new_status}'")
                last_status = new_status
                update_display()

if __name__ == "__main__":
    main()
