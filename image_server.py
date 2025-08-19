import http.server
import socketserver
import os
import logging
from time import strftime, localtime

# Configuration
PORT = 8000
IMAGE_PATH = '/tmp/ramdisk/clock_face.png'
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="1">
    <title>Clock Face Display</title>
</head>
<body style="background-color: black; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0;">
    <img src="/clock_face.png" alt="Clock Face" style="max-width: 100%; height: auto;">
</body>
</html>
"""

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/image_server.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class ImageRequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            # Serve the HTML page
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode('utf-8'))
        elif self.path == '/clock_face.png':
            # Serve the image file
            try:
                if os.path.exists(IMAGE_PATH):
                    with open(IMAGE_PATH, 'rb') as file:
                        self.send_response(200)
                        self.send_header('Content-type', 'image/png')
                        self.end_headers()
                        self.wfile.write(file.read())
                    logger.info(f"Served {IMAGE_PATH}")
                else:
                    self.send_error(404, f"File {IMAGE_PATH} not found")
                    logger.error(f"Image file {IMAGE_PATH} not found")
            except Exception as e:
                self.send_error(500, f"Error serving image: {e}")
                logger.error(f"Error serving {IMAGE_PATH}: {e}")
        else:
            self.send_error(404, "Not found")
            logger.warning(f"Invalid path requested: {self.path}")

def main():
    # Ensure log directory exists
    log_dir = os.path.dirname('logs/image_server.log')
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)
        logger.info(f"Created log directory: {log_dir}")

    # Check if image path is accessible
    if not os.path.exists(os.path.dirname(IMAGE_PATH)):
        logger.error(f"RAM disk directory {os.path.dirname(IMAGE_PATH)} does not exist. Ensure tmpfs is mounted.")
        return

    # Start the server
    with socketserver.TCPServer(("", PORT), ImageRequestHandler) as httpd:
        logger.info(f"Starting web server on port {PORT}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            logger.info("Shutting down web server")
            httpd.server_close()
        except Exception as e:
            logger.error(f"Server error: {e}")
            httpd.server_close()

if __name__ == "__main__":
    main()
