# DSM_GUI

Desktop control panel (Python + Tkinter) for DSMediaplay accounts. Runs on Windows and macOS.

## Run from source

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py                                        # optional: -j path/to/logins.json
```

## Accounts and passwords

Nothing secret is stored in this repository or in the build.

- On the first start the app asks for the language (Czech or English) and remembers it; it can be changed in *Settings*.
- **Customer accounts and logins** are added in the app with the **+** buttons next to the two drop-downs
  (an account needs a name and an `https://` address; a login is added to the selected account).
- **Account list** (customer name, URL, login - no passwords) is a JSON file in the per-user config folder:
  `%APPDATA%\DSM_GUI\logins.json` on Windows, `~/Library/Application Support/DSM_GUI/logins.json` on macOS.
  Use `login.example.json` as a template, or pass another file with `-j`.
- **Passwords** are stored in the operating system credential store (Windows Credential Manager / macOS Keychain)
  under the service `DSM_GUI`, per user. Enter them once in the app and press *Save login details*.
- A legacy config that still contains plaintext passwords is migrated automatically on first start:
  the passwords move to the credential store and are removed from the JSON file.

Changing a customer's URL invalidates its stored passwords (they are keyed by login and URL) - enter them again.

## Build

GitHub Actions (`Build` workflow, run manually or by pushing a `v*` tag) builds the Windows and macOS packages
with PyInstaller and attaches them to the run as artifacts. Running it manually with a `release_tag`
(e.g. `v1.0.0`), or pushing a `v*` tag, also publishes a GitHub release with `DSM_GUI-windows.zip` and/or
`DSM_GUI-macos.zip`. Locally:

```bash
pip install -r requirements-build.txt
pyinstaller --noconfirm DSM_GUI.spec                 # output in dist/
```

The builds are unsigned: Windows SmartScreen and macOS Gatekeeper will warn on first launch.
No administrator rights are needed to run them - unzip anywhere and start `DSM_GUI`.
