"""
Shows the main window and the table of players with invented accounts and players (nothing of a real account is on
them) and prints a line "SHOT <file> <x>,<y>,<width>,<height>" for each picture to take: the pictures for the
documentation, in both languages. `tools/capture_documentation_images.sh` takes them (macOS, `screencapture`).
"""
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, ".")
from gui_app import gui  # noqa: E402
from gui_app.player_browser import PlayerBrowser  # noqa: E402

IMAGES = os.path.join("documentation", "web_assets", "images")
NOW = datetime.now()


def stamp(minutes_ago):
    return int((NOW - timedelta(minutes=minutes_ago)).timestamp() * 1000)


def players():
    rows = [("Obchod Praha 01", True, "Obchod Praha", "Praha", ["vstup"], 3, 2, "hlavní vchod", 47.2, "5.3.1"),
            ("Obchod Praha 02", True, "Obchod Praha", "Praha", [], 7, 4, "", 51.0, "5.3.1"),
            ("Obchod Brno 01", False, "Obchod Brno", "Brno", ["vstup", "test"], 2600, 2590, "rozbitá obrazovka", None, "5.2.9"),
            ("Kancelář 01", True, "Kancelář", "Praha", [], 5, 3, "", 44.5, "5.3.1"),
            ("Sklad 01", False, "Sklad", "Ostrava", [], 900, 880, "čeká na výměnu", None, "5.2.9"),
            ("Lobby 01", True, "Lobby", "Praha", ["vstup"], 4, 1, "", 49.8, "5.3.1"),
            ("Lobby 02", True, "Lobby", "Praha", [], 6, 2, "", 53.4, "5.3.1"),
            ("Pobočka Plzeň 01", True, "Pobočky", "Plzeň", [], 8, 5, "", 46.1, "5.3.0")]
    return [{"_id": f"id{i}", "name": name, "isConnected": online, "group": {"name": group}, "configLocation": place,
             "labels": labels, "lastUpload": stamp(up), "lastReported": stamp(rep), "notes": note,
             **({"piTemperature": str(temp)} if temp else {}), "version": version}
            for i, (name, online, group, place, labels, up, rep, note, temp, version) in enumerate(rows)]


def shoot(window, name):
    """Shows the window and asks, on the standard output, for a picture of it; the picture is taken by the caller
    (a program started from a terminal may not take pictures of the screen itself, `screencapture` of the shell may)."""
    window.lift()
    window.focus_force()
    for _ in range(40):
        window.update()
        time.sleep(0.02)
    box = f"{window.winfo_rootx()},{window.winfo_rooty()},{window.winfo_width()},{window.winfo_height()}"
    print(f"SHOT {name} {box}", flush=True)
    end = time.monotonic() + 3  # the window stays as it is while the picture is taken
    while time.monotonic() < end:
        window.update()
        time.sleep(0.02)


def main(language: str):
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "logins.json")
    account = "Ukázkový účet" if language == "cz" else "Sample account"
    with open(path, "w", encoding="utf-8") as file:
        json.dump({"lang": language, "font": ["Helvetica", 12], "default": [account, "demo"],
                   "logins": {account: {"url": "https://demo.example.com", "names": {"demo": {"login": "demo"}},
                                        "last": "demo"}}}, file)
    with patch("gui_app.gui.credentials.get_password", return_value="heslo"):
        app = gui.DSMediaplayApp(path)
    app.geometry("+60+60")
    app.update()
    app.entity_type_var.set("Groups")
    app.update_action_selection()
    label = next(l for l, k in app.entity_actions["Groups"].items() if k == "set_detailed_playlists_to_groups")
    app.option_choose_action.set(label)
    app.update_input_button()
    shoot(app, f"main_window_{language}.png")

    browser = PlayerBrowser(app, url="u", login="l", password="p", account_name=account, fetch=lambda *a: players(),
                            hidden_columns=["synced", "note", "label", "temperature", "version"])
    browser.geometry("1000x420+80+120")
    end = time.monotonic() + 10
    while browser._loading and time.monotonic() < end:
        app.update()
        time.sleep(0.01)
    shoot(browser, f"players_table_{language}.png")
    browser.destroy()
    app.destroy()


if __name__ == "__main__":
    main(sys.argv[1])
