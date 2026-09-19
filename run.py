import argparse
import threading
from gui_app.gui import DSMediaplayApp
from documentation.server import run_server
from util.paths import default_logins_file


def start_server(js):
    run_server(js)


def main():
    parser = argparse.ArgumentParser(description='Launch DSMediaplayApp with optional JSON file.')
    parser.add_argument('-j', '--json', type=str, default=None,
                        help='Path to the accounts JSON file (default: per-user config folder)')

    args = parser.parse_args()
    logins_file = args.json or str(default_logins_file())
    server_thread = threading.Thread(target=start_server, args=(logins_file,))
    server_thread.daemon = True  # Thread will exit when the main program exits
    server_thread.start()

    app = DSMediaplayApp(logins_file)
    app.mainloop()


if __name__ == "__main__":
    main()

