import http.server
import json
import socketserver
import os
from documentation.server_logger import ServerLogger
from util.paths import resource_path

PORT = 8080
bound_port = None  # the port the server listens on, once it does: PORT, or another one when something else has PORT

# Define the base directories for the server
PAGES_DIR = resource_path('documentation/pages')
ASSETS_DIR = resource_path('documentation/web_assets')


class DocumentationServer(socketserver.TCPServer):
    # Without this a quick restart of the app fails to bind while the old socket sits in TIME_WAIT. Not on Windows:
    # there it lets a second socket bind a port that is being listened on, so a busy port would never be noticed
    allow_reuse_address = os.name != "nt"


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


def load_config(config_path) -> dict:
    """The JSON configuration; a missing, unreadable or damaged file only means the defaults (the help is not to die
    of it, and it may not exist yet on the first start)."""
    try:
        with open(config_path, 'r', encoding='utf-8') as config_file:
            config = json.load(config_file)
    except (OSError, ValueError):
        return {}
    return config if isinstance(config, dict) else {}


def bind_server():
    """
    The server on PORT, or on a free port when PORT is taken (by another application: the help must not open that
    one's pages instead of its own); None when no port can be had. Localhost only: the documentation must not be
    reachable from the network.
    """
    global bound_port
    for port in (PORT, 0):
        try:
            httpd = DocumentationServer(("127.0.0.1", port), CustomHTTPRequestHandler)
        except OSError:
            continue
        bound_port = httpd.server_address[1]
        return httpd
    return None


def run_server(config_path):
    """Run the HTTP server; the JSON configuration file is optional."""
    config = load_config(config_path)

    # Initialize the logger with the parsed configuration
    global log
    log = ServerLogger(config=config, log_name="http_server").get_logger()

    httpd = bind_server()
    if httpd is None:
        log.error("Documentation server not started: no port is available")
        return
    with httpd:
        log.info(f"Serving at port {bound_port}")
        httpd.serve_forever()


if __name__ == '__main__':
    # Specify the path to the JSON configuration file
    CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')
    run_server(CONFIG_PATH)
