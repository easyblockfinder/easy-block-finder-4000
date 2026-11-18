; Easy Block Finder 4000 — Windows installer (Inno Setup 6)
; Built by scripts\build_windows_release.ps1
;
; Defines (passed by build script):
;   MyAppVersion  e.g. 1.0.7
;   PayloadDir    absolute path to assembled payload folder
;   DistDir       absolute path for OutputDir

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef PayloadDir
  #define PayloadDir "..\dist\payload"
#endif
#ifndef DistDir
  #define DistDir "..\dist"
#endif

#define MyAppName "Easy Block Finder 4000"
#define MyAppShort "EBF4000"
#define MyAppPublisher "Easy Block Finder 4000"
#define MyAppURL "https://easyblockfinder.com/"
#define MyAppExeName "EBF4000.exe"

[Setup]
AppId={{A8E4B0C1-9F2D-4E6A-8B31-EBF4000SETUP01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppShort} - v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL=https://github.com/easyblockfinder/easy-block-finder-4000/releases
DefaultDirName={localappdata}\EasyBlockFinder4000\app
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile={#PayloadDir}\LICENSE
InfoBeforeFile={#PayloadDir}\DISCLAIMER.md
OutputDir={#DistDir}
OutputBaseFilename=EBF4000-v{#MyAppVersion}-windows-setup
#ifexist "{#PayloadDir}\assets\ebf4000_icon.ico"
SetupIconFile={#PayloadDir}\assets\ebf4000_icon.ico
#endif
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#ifexist "{#PayloadDir}\assets\ebf4000_icon.ico"
UninstallDisplayIcon={app}\assets\ebf4000_icon.ico
#endif
CloseApplications=yes
RestartApplications=no
ChangesEnvironment=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce
Name: "addpath"; Description: "Add bundled Python to your user &PATH"; GroupDescription: "Environment:"; Flags: checkedonce

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
#ifexist "{#PayloadDir}\assets\ebf4000_icon.ico"
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\ebf4000_icon.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\ebf4000_icon.ico"; Tasks: desktopicon
#else
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon
#endif
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent shellexec
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\add_python_user_path.ps1"" -PythonExe ""{app}\runtime\python.exe"" -Quiet"; StatusMsg: "Adding bundled Python to user PATH..."; Tasks: addpath; Flags: runhidden waituntilterminated

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.deps_ok"
Type: filesandordirs; Name: "{app}\runtime\.deps_ok"

[Code]
function NeedsAddPath(Param: string): boolean;
begin
  Result := True;
end;
