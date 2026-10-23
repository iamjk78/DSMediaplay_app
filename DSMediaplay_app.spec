# PyInstaller build definition, identical for Windows and macOS: pyinstaller --noconfirm DSMediaplay_app.spec
# Only read-only resources are bundled. Accounts and passwords are never part of the build
# (accounts live in the per-user config folder, passwords in the OS credential store).
import sys

sys.path.insert(0, SPECPATH)  # the repository: the version is written in util/version.py only
from util.version import VERSION

a = Analysis(
    ["run.py"],
    datas=[
        ("assets", "assets"),
        ("documentation/pages", "documentation/pages"),
        ("documentation/web_assets", "documentation/web_assets"),
    ],
)
pyz = PYZ(a.pure)
version_info = None
if sys.platform == "win32":  # the file properties of the .exe (Details), from the same version
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                     VarFileInfo, VarStruct, VSVersionInfo)
    parts = [int(part) for part in VERSION.split(".")]
    numbers = tuple(parts + [0] * (4 - len(parts)))
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[StringFileInfo([StringTable("040904B0", [
            StringStruct("ProductName", "DSMediaplay_app"), StringStruct("FileDescription", "DSMediaplay_app"),
            StringStruct("FileVersion", VERSION), StringStruct("ProductVersion", VERSION)])]),
              VarFileInfo([VarStruct("Translation", [1033, 1200])])])

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DSMediaplay_app",
    console=False,
    icon="assets/app.ico" if sys.platform == "win32" else None,  # regenerate with packaging/make_icons.py
    version=version_info,
)
coll = COLLECT(exe, a.binaries, a.datas, name="DSMediaplay_app")

if sys.platform == "darwin":
    app = BUNDLE(coll, name="DSMediaplay_app.app", bundle_identifier="media.bluetouch.dsm-gui", icon="assets/app.icns",
                 version=VERSION)
