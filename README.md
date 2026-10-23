# DSMediaplay_app

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

## User guide

The guide that the Help button opens (`documentation/pages/cz` and `/en`) is generated, not written by hand: the names of the
buttons and actions, the input templates and the list of the actions come from the application itself, the other texts are in
`tools/documentation_texts.py`. After changing an action or a text run

```bash
python tools/generate_documentation.py
```

and commit the pages (a test fails when they are not up to date). The pictures in the guide are taken by
`tools/capture_documentation_images.sh` (macOS, with invented data).

## Releasing

The version of the application is in `util/version.py`. A release is a tag `v<that version>` (the build refuses any other); change the
version, commit, then tag and push the tag, or run the `Build` workflow with `release_tag`.

## Build

GitHub Actions (`Build` workflow, run manually or by pushing a `v*` tag) builds the Windows installer
(`DSMediaplay_app-Setup-<version>.exe`, Inno Setup) and the macOS app with PyInstaller and attaches them to the run as artifacts.
Running it manually with a `release_tag` (e.g. `v1.0.0`), or pushing a `v*` tag, also publishes a GitHub release
with the installer and/or the macOS disk image `DSMediaplay_app-<version>-macos.dmg` (drag the app to *Applications*; the workflow mounts it and starts the app from it) and `DSMediaplay_app-macos.zip`. On Windows the workflow installs the installer silently, starts the
installed app, installs over it again (a running instance included) and uninstalls it again before the build counts as successful.
The tests (`pip install -r requirements-dev.txt`, `python -m pytest`) run on Windows and macOS and the dependencies are audited
for known vulnerabilities; a release is published only when the build, the tests and the audit all pass, and only from a commit
on `main`. Every build starts the application with `--self-test` (window, texts and credential store) before it counts as working. Locally:

```bash
pip install -r requirements-build.txt
pyinstaller --noconfirm DSMediaplay_app.spec                 # output in dist/
```

The installer needs no administrator rights: it installs for the current user
(`%LOCALAPPDATA%\Programs\DSMediaplay_app`), adds a Start menu shortcut (optionally a desktop one) and an entry in
*Apps & features* for uninstalling. Uninstalling keeps your account list and saved passwords, so a reinstall
picks them up again. Installing a newer version over an installed one first uninstalls the old version (closing it if it is
running), so no file of it is left behind; the account list and the passwords stay.

The app icon comes from `assets/ds_media_icon.jpg`; `python packaging/make_icons.py` regenerates
`assets/app.ico` and `assets/app.icns` from it (a larger source image gives sharper large icons).

The builds are unsigned: Windows SmartScreen and macOS Gatekeeper will warn on first launch.
The macOS build is a zip with `DSMediaplay_app.app`.
