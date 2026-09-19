; Per-user installer for Windows (no administrator rights needed), built by the GitHub Actions workflow:
;   ISCC.exe /DAppVersion=1.0.0 /DAppNumericVersion=1.0.0.0 packaging\installer.iss
; Expects the PyInstaller output in dist\DSM_GUI. The account list in %APPDATA%\DSM_GUI and the passwords in
; Windows Credential Manager are user data: the uninstaller leaves them, so a reinstall keeps them.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef AppNumericVersion
  #define AppNumericVersion "0.0.0.0"
#endif
#define AppName "DSMediaplay Control Panel"
#define AppExe "DSM_GUI.exe"

[Setup]
; Fixed identifier: it is what makes a newer installer upgrade the installed app instead of installing beside it
AppId={{DB940A40-CA4A-48BB-B2CA-1A0D44974506}
AppName={#AppName}
AppVersion={#AppVersion}
VersionInfoVersion={#AppNumericVersion}
AppPublisher=JKRE - BlueTouch Media
DefaultDirName={autopf}\DSM_GUI
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=..\dist-installer
OutputBaseFilename=DSM_GUI-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "czech"; MessagesFile: "compiler:Languages\Czech.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\DSM_GUI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
