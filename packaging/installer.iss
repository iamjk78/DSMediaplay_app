; Per-user installer for Windows (no administrator rights needed), built by the GitHub Actions workflow:
;   ISCC.exe /DAppVersion=1.0.0 /DAppNumericVersion=1.0.0.0 packaging\installer.iss
; Expects the PyInstaller output in dist\DSMediaplay_app. The account list in %APPDATA%\DSM_GUI and the passwords in
; Windows Credential Manager are user data: the uninstaller leaves them, so a reinstall keeps them.
; An already installed version is uninstalled first (see [Code]), so nothing of it is left behind in the folder.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef AppNumericVersion
  #define AppNumericVersion "0.0.0.0"
#endif
#define AppName "DSMediaplay_app"
#define AppExe "DSMediaplay_app.exe"

[Setup]
; Fixed identifier: it is what makes a newer installer upgrade the installed app instead of installing beside it
AppId={{DB940A40-CA4A-48BB-B2CA-1A0D44974506}
AppName={#AppName}
AppVersion={#AppVersion}
VersionInfoVersion={#AppNumericVersion}
AppPublisher=JKRE - BlueTouch Media
DefaultDirName={autopf}\DSMediaplay_app
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=..\dist-installer
OutputBaseFilename=DSMediaplay_app-Setup-{#AppVersion}
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
Source: "..\dist\DSMediaplay_app\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[CustomMessages]
czech.RemovingOldVersion=Odstraňuji dříve nainstalovanou verzi...
english.RemovingOldVersion=Removing the previously installed version...
czech.OldVersionNotRemoved=Dříve nainstalovanou verzi se nepodařilo zcela odstranit. Nová verze se nainstaluje přes ni.
english.OldVersionNotRemoved=The previously installed version could not be removed completely. The new version is installed over it.

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; The update started from the application (/SILENT /RELAUNCH=1) starts the new version when it is done
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: RelaunchRequested

[Code]
const
  // The key Inno Setup writes for the AppId above (AppId + _is1)
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{DB940A40-CA4A-48BB-B2CA-1A0D44974506}_is1';
  RemovalTimeoutMs = 60000;

function RelaunchRequested(): Boolean;
begin
  Result := ExpandConstant('{param:RELAUNCH|0}') = '1';
end;

function InstalledUninstaller(): String;
var
  UninstallString: String;
begin
  Result := '';
  { HKA is the current user for this per-user installer, the whole machine when it runs with /ALLUSERS }
  if RegQueryStringValue(HKA, UninstallKey, 'UninstallString', UninstallString) then
  begin
    if (Length(UninstallString) >= 2) and (UninstallString[1] = '"') and (UninstallString[Length(UninstallString)] = '"') then
      UninstallString := Copy(UninstallString, 2, Length(UninstallString) - 2);
    Result := UninstallString;
  end;
end;

procedure StopRunningApplication();
var
  ResultCode: Integer;
begin
  { First the polite request (the window closes), then whatever is still running; 128 = it was not running }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM {#AppExe}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  if ResultCode = 0 then
    Sleep(3000);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#AppExe}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function OldVersionIsGone(const Uninstaller: String): Boolean;
begin
  Result := (not FileExists(Uninstaller)) and (not RegKeyExists(HKA, UninstallKey));
end;

procedure RemoveInstalledVersion();
var
  Uninstaller: String;
  ResultCode, Waited: Integer;
begin
  Uninstaller := InstalledUninstaller();
  { Nothing installed, or only a leftover registry entry without its uninstaller: the installation goes on as usual }
  if (Uninstaller = '') or (not FileExists(Uninstaller)) then
    Exit;

  WizardForm.StatusLabel.Caption := CustomMessage('RemovingOldVersion');
  StopRunningApplication();
  Exec(Uninstaller, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

  { The uninstaller carries on in a temporary copy of itself, so wait until it has finished }
  Waited := 0;
  while (not OldVersionIsGone(Uninstaller)) and (Waited < RemovalTimeoutMs) do
  begin
    Sleep(500);
    Waited := Waited + 500;
  end;

  if not OldVersionIsGone(Uninstaller) then
  begin
    Log('The previously installed version was not removed completely, the new one is installed over it.');
    if not WizardSilent then
      MsgBox(CustomMessage('OldVersionNotRemoved'), mbInformation, MB_OK);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  { The first thing of the installation itself: the files of the new version go into a clean folder }
  if CurStep = ssInstall then
    RemoveInstalledVersion();
end;
