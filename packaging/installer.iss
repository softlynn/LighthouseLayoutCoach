; Inno Setup installer for LighthouseLayoutCoach

#define MyAppName "LighthouseLayoutCoach"
#define MyAppExeName "LighthouseLayoutCoach.exe"
#define MyAppPublisher "Softlynn"
#ifndef MyAppVersion
#define MyAppVersion "0.0.0"
#endif

[Setup]
AppId={{7E4C4B30-0E73-4C9A-B7B0-1E1C1E7D58D1}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://github.com/Softlynn/LighthouseLayoutCoach
AppSupportURL=https://github.com/Softlynn/LighthouseLayoutCoach/issues
AppUpdatesURL=https://github.com/Softlynn/LighthouseLayoutCoach/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputBaseFilename=LighthouseLayoutCoach_Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\installer\installer_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Lighthouse Layout Coach (Launcher)"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Lighthouse Layout Coach (Desktop)"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--desktop"
Name: "{group}\Lighthouse Layout Coach (VR Overlay)"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--vr"
Name: "{commondesktop}\Lighthouse Layout Coach"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Lighthouse Layout Coach"; Flags: nowait postinstall skipifsilent
