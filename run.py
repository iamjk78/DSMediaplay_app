import sys

# Must run before Tk is loaded (the "gui_app.gui" import below does that): without it, Windows treats the process
# as DPI-unaware and scales the whole window as a bitmap above 100% display scaling, so native widgets (comboboxes)
# and the canvas-free buttons end up sized against different, mismatched pixel grids and overlap.
if sys.platform == "win32":
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
    except (AttributeError, OSError):
        pass

import argparse
import threading
from gui_app.gui import DSMediaplayApp
from documentation.server import run_server
from util.paths import default_logins_file


def start_server(js):
    run_server(js)


def self_test() -> int:
    """
    Builds the main window on an empty temporary configuration and asks the credential store, then ends: 0 when the
    application can start at all (Tk, the bundled texts and the credential store backend work), 1 when it cannot.
    The build checks use this: a window that never gets built is not seen by a test of the documentation server.
    """
    import json
    import os
    import tempfile
    import keyring
    from keyring.errors import KeyringError
    try:
        with tempfile.TemporaryDirectory() as folder:
            config = os.path.join(folder, "logins.json")
            with open(config, "w", encoding="utf-8") as file:
                json.dump({"lang": "cz", "font": ["Helvetica", 12], "default": ["", ""], "logins": {}}, file)
            app = DSMediaplayApp(config)
            app.withdraw()
            app.update()
            app.destroy()
        if type(keyring.get_keyring()).__module__.endswith(".fail"):
            raise KeyringError("no credential store backend is available")
        keyring.get_password("DSM_GUI-self-test", "nobody")  # nothing is stored under this; it must only not fail
    except Exception as error:
        print(f"Self-test failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print("Self-test passed")
    return 0


def main():
    parser = argparse.ArgumentParser(description='Launch DSMediaplayApp with optional JSON file.')
    parser.add_argument('-j', '--json', type=str, default=None,
                        help='Path to the accounts JSON file (default: per-user config folder)')
    parser.add_argument('--self-test', action='store_true',
                        help='Check that the application can start (window, texts, credential store) and exit')

    args = parser.parse_args()
    if args.self_test:
        sys.exit(self_test())
    logins_file = args.json or str(default_logins_file())
    server_thread = threading.Thread(target=start_server, args=(logins_file,))
    server_thread.daemon = True  # Thread will exit when the main program exits
    server_thread.start()

    app = DSMediaplayApp(logins_file)
    app.mainloop()


if __name__ == "__main__":
    main()

