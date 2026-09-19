# PyInstaller build definition, identical for Windows and macOS: pyinstaller --noconfirm DSMediaplay_app.spec
# Only read-only resources are bundled. Accounts and passwords are never part of the build
# (accounts live in the per-user config folder, passwords in the OS credential store).
import sys

a = Analysis(
    ["run.py"],
    datas=[
        ("assets", "assets"),
        ("documentation/pages", "documentation/pages"),
        ("documentation/web_assets", "documentation/web_assets"),
    ],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DSMediaplay_app",
    console=False,
    icon="assets/app.ico" if sys.platform == "win32" else None,  # regenerate with packaging/make_icons.py
)
coll = COLLECT(exe, a.binaries, a.datas, name="DSMediaplay_app")

if sys.platform == "darwin":
    app = BUNDLE(coll, name="DSMediaplay_app.app", bundle_identifier="media.bluetouch.dsm-gui", icon="assets/app.icns")
