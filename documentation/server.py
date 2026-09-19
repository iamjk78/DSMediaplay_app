import http.server
import json
import socketserver
import os
from documentation.server_logger import ServerLogger
from util.paths import resource_path

PORT = 8080

# Define the base directories for the server
PAGES_DIR = resource_path('documentation/pages')
ASSETS_DIR = resource_path('documentation/web_assets')


class DocumentationServer(socketserver.TCPServer):
    # Without this a quick restart of the app fails to bind while the old socket sits in TIME_WAIT
    allow_reuse_address = True


class CustomHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):

    def resolve_path(self, path):
        """Resolve the file path based on the requested URL."""
        path_parts = path.lstrip('/').split('/')

        if len(path_parts) > 1 and path_parts[0] in ['en', 'cz']:
            language = path_parts[0]
            path_parts = path_parts[1:]
        else:
            language = 'en'

        # Resolve path for assets or pages based on language
        if path_parts[0] == 'assets':
            base, parts = ASSETS_DIR, path_parts[1:]
        elif path_parts == ['']:
            base, parts = PAGES_DIR / language, ["index.html"]
        else:
            base, parts = PAGES_DIR / language, path_parts

        resolved = os.path.realpath(os.path.join(base, *parts))
        if os.path.commonpath([resolved, os.path.realpath(base)]) != os.path.realpath(base):
            return None  # e.g. "../" segments trying to leave the served folder
        return resolved

    def do_GET(self):
        """Handle GET requests."""
        file_path = self.resolve_path(self.path)
        log.info(f"Serving file: {file_path}")

        if file_path and os.path.isfile(file_path):
            self.serve_file(file_path)
        else:
            self.send_error(404, "File not found")

    def serve_file(self, file_path):
        """Serve the requested file to the client."""
        with open(file_path, 'rb') as file:
            self.send_response(200)
            self.send_header('Content-type', self.guess_type(file_path))
            self.end_headers()
            self.wfile.write(file.read())


def run_server(config_path):
    """Run the HTTP server; the JSON configuration file is optional (it may not exist on first start)."""
    config = {}
    if os.path.exists(config_path):
        with open(config_path, 'r') as config_file:
            config = json.load(config_file)

    # Initialize the logger with the parsed configuration
    global log
    log = ServerLogger(config=config, log_name="http_server").get_logger()

    # Define the request handler
    handler = CustomHTTPRequestHandler
    # Localhost only: the documentation must not be reachable from the network
    try:
        httpd = DocumentationServer(("127.0.0.1", PORT), handler)
    except OSError as error:
        log.error(f"Documentation server not started, port {PORT} is unavailable: {error}")
        return
    with httpd:
        log.info(f"Serving at port {PORT}")
        httpd.serve_forever()


if __name__ == '__main__':
    # Specify the path to the JSON configuration file
    CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')
    run_server(CONFIG_PATH)
